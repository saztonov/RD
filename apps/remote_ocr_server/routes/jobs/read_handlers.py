"""Обработчики чтения задач OCR"""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import Header, HTTPException, Query

from apps.remote_ocr_server.routes.common import (
    check_api_key,
    get_file_icon,
    get_r2_storage,
)
from apps.remote_ocr_server.storage import (
    get_job,
    get_job_file_by_type,
    job_to_dict,
    list_jobs,
    list_jobs_changed_since,
)

_logger = logging.getLogger(__name__)


def list_jobs_handler(
    document_id: Optional[str] = None,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> list:
    """Получить список задач"""
    check_api_key(x_api_key)

    jobs = list_jobs(document_id)
    return [
        {
            "id": j.id,
            "status": j.status,
            "progress": j.progress,
            "document_name": j.document_name,
            "task_name": j.task_name,
            "document_id": j.document_id,
            "created_at": j.created_at,
            "updated_at": j.updated_at,
            "error_message": j.error_message,
            "node_id": j.node_id,
        }
        for j in jobs
    ]


def get_jobs_changes_handler(
    since: str = Query(..., description="ISO timestamp для фильтрации изменений"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить задачи, изменённые после указанного времени."""
    check_api_key(x_api_key)

    jobs = list_jobs_changed_since(since)
    return {
        "jobs": [
            {
                "id": j.id,
                "status": j.status,
                "progress": j.progress,
                "document_name": j.document_name,
                "task_name": j.task_name,
                "document_id": j.document_id,
                "created_at": j.created_at,
                "updated_at": j.updated_at,
                "error_message": j.error_message,
                "node_id": j.node_id,
            }
            for j in jobs
        ],
        "server_time": datetime.utcnow().isoformat(),
    }


def get_job_handler(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить информацию о задаче"""
    check_api_key(x_api_key)

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return job_to_dict(job)


def _add_job_settings_and_r2_files(result: dict, job) -> dict:
    """Добавить настройки и R2 файлы к результату"""
    if job.settings:
        result["job_settings"] = {
            "text_model": job.settings.text_model,
            "table_model": job.settings.table_model,
            "image_model": job.settings.image_model,
            "stamp_model": job.settings.stamp_model,
        }
    else:
        result["job_settings"] = {}

    r2_public_url = os.getenv("R2_PUBLIC_URL")
    if r2_public_url and job.r2_prefix:
        base_url = r2_public_url.rstrip("/")
        result["r2_base_url"] = f"{base_url}/{job.r2_prefix}"
        result["r2_files"] = [
            {
                "name": f.file_name,
                "path": f.r2_key.replace(f"{job.r2_prefix}/", ""),
                "icon": get_file_icon(f.file_type),
            }
            for f in job.files
        ]
    else:
        result["r2_base_url"] = None
        result["r2_files"] = []

    return result


def get_job_details_handler(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить детальную информацию о задаче"""
    check_api_key(x_api_key)

    job = get_job(job_id, with_files=True, with_settings=True)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job_to_dict(job)

    # Используем сохранённую статистику из БД если есть
    if job.block_stats:
        # Добавляем время обработки из started_at/completed_at
        if job.started_at and job.completed_at:
            try:
                started = datetime.fromisoformat(job.started_at.replace("Z", "+00:00"))
                completed = datetime.fromisoformat(job.completed_at.replace("Z", "+00:00"))
                processing_time = (completed - started).total_seconds()
                job.block_stats["processing_time_seconds"] = processing_time
                total_blocks = job.block_stats.get("total", 0)
                if total_blocks > 0:
                    job.block_stats["avg_time_per_block"] = processing_time / total_blocks
            except Exception as e:
                _logger.warning(f"Failed to calculate processing time: {e}")
        result["block_stats"] = job.block_stats
        return _add_job_settings_and_r2_files(result, job)

    # Fallback: вычисляем на лету для старых задач
    total_time_seconds = None
    if job.created_at and job.updated_at:
        try:
            created = datetime.fromisoformat(job.created_at.replace("Z", "+00:00"))
            updated = datetime.fromisoformat(job.updated_at.replace("Z", "+00:00"))
            total_time_seconds = (updated - created).total_seconds()
        except Exception as e:
            _logger.warning(f"Failed to calculate job duration: {e}")

    blocks_file = get_job_file_by_type(job_id, "blocks")
    if blocks_file:
        try:
            r2 = get_r2_storage()
            blocks_text = r2.download_text(blocks_file.r2_key)
            if blocks_text:
                blocks = json.loads(blocks_text)

                # Подсчёт блоков по типам
                text_count = sum(1 for b in blocks if b.get("block_type") == "text")

                # Image блоки: разделяем на штампы и обычные изображения
                image_blocks = [b for b in blocks if b.get("block_type") == "image"]
                stamp_count = sum(1 for b in image_blocks if b.get("category_code") == "stamp")
                image_count = len(image_blocks) - stamp_count  # Обычные изображения (не штампы)

                total_blocks = len(blocks)
                grouped_count = text_count

                # Статистика по блокам
                block_stats = {
                    "total": total_blocks,
                    "text": text_count,
                    "image": image_count,
                    "stamp": stamp_count,
                    "grouped": grouped_count,
                }

                # Добавляем статистику по времени если задача завершена
                if total_time_seconds is not None and total_time_seconds > 0:
                    block_stats["total_time_seconds"] = total_time_seconds

                    # Среднее время на блок (для всех блоков)
                    if total_blocks > 0:
                        block_stats["avg_time_per_block"] = total_time_seconds / total_blocks

                    # Среднее время на текстовый блок
                    if grouped_count > 0:
                        block_stats["avg_time_per_text_block"] = total_time_seconds / grouped_count

                    # Примерное распределение времени по типам блоков
                    # (на основе весов: текст=1, image=2, stamp=0.5)
                    weight_text = text_count * 1.0
                    weight_image = image_count * 2.0
                    weight_stamp = stamp_count * 0.5
                    total_weight = weight_text + weight_image + weight_stamp

                    if total_weight > 0:
                        time_per_weight = total_time_seconds / total_weight
                        block_stats["estimated_text_time"] = weight_text * time_per_weight
                        block_stats["estimated_image_time"] = weight_image * time_per_weight
                        block_stats["estimated_stamp_time"] = weight_stamp * time_per_weight

                result["block_stats"] = block_stats
        except Exception as e:
            _logger.warning(f"Failed to load blocks from R2: {e}")
    elif total_time_seconds is not None:
        # Если нет блоков, но есть время - добавляем только время
        result["block_stats"] = {"total_time_seconds": total_time_seconds}

    return _add_job_settings_and_r2_files(result, job)


def get_job_progress_handler(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить детальный прогресс задачи с информацией о фазах обработки"""
    check_api_key(x_api_key)

    job = get_job(job_id, with_files=True)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    _logger.debug(
        f"[get_job_progress] job_id={job_id[:8]}, status={job.status}, "
        f"progress={job.progress}, phase_data={bool(job.phase_data)}"
    )

    result = {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "status_message": job.status_message,
        "phase_data": job.phase_data,
        "error_message": job.error_message,
    }

    # Добавляем информацию о блоках если есть
    # Сначала пробуем annotation.json (с результатами OCR), потом blocks.json
    blocks = None
    annotation_file = get_job_file_by_type(job_id, "annotation")
    if annotation_file:
        try:
            r2 = get_r2_storage()
            annotation_text = r2.download_text(annotation_file.r2_key)
            if annotation_text:
                blocks = json.loads(annotation_text)
                _logger.debug(f"[get_job_progress] Loaded {len(blocks)} blocks from annotation.json")
        except Exception as e:
            _logger.warning(f"Failed to load annotation for progress: {e}")

    # Fallback на blocks.json если annotation.json недоступен
    if blocks is None:
        blocks_file = get_job_file_by_type(job_id, "blocks")
        if blocks_file:
            try:
                r2 = get_r2_storage()
                blocks_text = r2.download_text(blocks_file.r2_key)
                if blocks_text:
                    blocks = json.loads(blocks_text)
                    _logger.debug(f"[get_job_progress] Loaded {len(blocks)} blocks from blocks.json (fallback)")
            except Exception as e:
                _logger.warning(f"Failed to load blocks for progress: {e}")

    if blocks:
        result["blocks"] = blocks
        # Логируем количество блоков с ocr_text
        blocks_with_ocr = sum(1 for b in blocks if b.get("ocr_text"))
        _logger.debug(f"[get_job_progress] Blocks with ocr_text: {blocks_with_ocr}/{len(blocks)}")

    # Добавляем URLs для кропов если доступны
    r2_public_url = os.getenv("R2_PUBLIC_URL")
    if r2_public_url and job.r2_prefix:
        base_url = r2_public_url.rstrip("/")
        result["r2_base_url"] = f"{base_url}/{job.r2_prefix}"

        # Собираем URLs для кропов
        crop_files = [f for f in job.files if f.file_type == "crop"]
        result["crops"] = [
            {
                "block_id": f.metadata.get("block_id") if f.metadata else None,
                "url": f"{base_url}/{f.r2_key}",
                "file_name": f.file_name,
            }
            for f in crop_files
        ]

    return result


def download_result_handler(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить ссылку на результат"""
    check_api_key(x_api_key)

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "done":
        raise HTTPException(
            status_code=400, detail=f"Job not ready, status: {job.status}"
        )

    result_file = get_job_file_by_type(job_id, "result_zip")
    if not result_file:
        raise HTTPException(status_code=404, detail="Result file not found")

    try:
        r2 = get_r2_storage()
        url = r2.generate_presigned_url(result_file.r2_key, expiration=3600)
        return {"download_url": url, "file_name": result_file.file_name}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate download URL: {e}"
        )
