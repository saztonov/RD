"""Celery задачи для OCR обработки"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import traceback
from pathlib import Path

from .celery_app import celery_app
from .memory_utils import force_gc, log_memory, log_memory_delta
from .rate_limiter import get_datalab_limiter
from .settings import settings
from .storage import Job, get_job, register_ocr_results_to_node, update_job_status
from .task_helpers import check_paused, create_empty_result, download_job_files
from .task_ocr_twopass import run_two_pass_ocr
from .task_results import generate_results
from .task_upload import upload_results_to_r2
from .worker_pdf import clear_page_size_cache

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="run_ocr_task", max_retries=3, rate_limit="4/m")
def run_ocr_task(self, job_id: str) -> dict:
    """Celery задача для обработки OCR"""
    start_mem = log_memory(f"[START] Задача {job_id}")

    work_dir = None
    try:
        # Получаем задачу из БД с настройками
        job = get_job(job_id, with_files=True, with_settings=True)
        if not job:
            logger.error(f"Задача {job_id} не найдена")
            return {"status": "error", "message": "Job not found"}

        if check_paused(job.id):
            return {"status": "paused"}

        # Обновляем статус на processing
        update_job_status(job.id, "processing", progress=0.05, status_message="📥 Инициализация задачи...")

        # Создаём временную директорию
        work_dir = Path(tempfile.mkdtemp(prefix=f"ocr_job_{job.id}_"))
        crops_dir = work_dir / "crops"
        crops_dir.mkdir(exist_ok=True)

        logger.info(f"Задача {job.id}: скачивание файлов из R2...")
        update_job_status(job.id, "processing", progress=0.06, status_message="📥 Скачивание файлов из R2...")
        pdf_path, blocks_path = download_job_files(job, work_dir)
        log_memory_delta("После скачивания файлов", start_mem)

        with open(blocks_path, "r", encoding="utf-8") as f:
            blocks_data = json.load(f)

        # annotation.json имеет структуру {pdf_path, pages: [{blocks: [...]}]}
        # Извлекаем блоки из всех страниц
        if isinstance(blocks_data, dict) and "pages" in blocks_data:
            all_blocks = []
            for page in blocks_data.get("pages", []):
                all_blocks.extend(page.get("blocks", []))
            blocks_data = all_blocks

        if not blocks_data:
            update_job_status(job.id, "done", progress=1.0, status_message="✅ Нет блоков для распознавания")
            create_empty_result(job, work_dir, pdf_path)
            upload_results_to_r2(job, work_dir)
            return {"status": "done", "job_id": job_id}

        from rd_core.models import Block
        from rd_core.ocr import create_ocr_engine

        blocks = [Block.from_dict(b, migrate_ids=False)[0] for b in blocks_data]
        total_blocks = len(blocks)

        logger.info(f"Задача {job.id}: {total_blocks} блоков")

        if check_paused(job.id):
            return {"status": "paused"}

        update_job_status(job.id, "processing", progress=0.1, status_message=f"⚙️ Подготовка: {total_blocks} блоков")

        # Настройки из Supabase
        job_settings = job.settings
        text_model = (job_settings.text_model if job_settings else "") or ""
        table_model = (job_settings.table_model if job_settings else "") or ""
        image_model = (job_settings.image_model if job_settings else "") or ""
        stamp_model = (job_settings.stamp_model if job_settings else "") or ""

        engine = job.engine or "openrouter"
        datalab_limiter = get_datalab_limiter() if engine == "datalab" else None

        if engine == "datalab" and settings.datalab_api_key:
            strip_backend = create_ocr_engine(
                "datalab",
                api_key=settings.datalab_api_key,
                rate_limiter=datalab_limiter,
                poll_interval=settings.datalab_poll_interval,
                poll_max_attempts=settings.datalab_poll_max_attempts,
                max_retries=settings.datalab_max_retries,
            )
        elif settings.openrouter_api_key:
            strip_model = text_model or table_model or "qwen/qwen3-vl-30b-a3b-instruct"
            strip_backend = create_ocr_engine(
                "openrouter",
                api_key=settings.openrouter_api_key,
                model_name=strip_model,
            )
        else:
            strip_backend = create_ocr_engine("dummy")

        if settings.openrouter_api_key:
            img_model = (
                image_model
                or text_model
                or table_model
                or "qwen/qwen3-vl-30b-a3b-instruct"
            )
            logger.info(f"IMAGE модель: {img_model}")
            image_backend = create_ocr_engine(
                "openrouter", api_key=settings.openrouter_api_key, model_name=img_model
            )

            stmp_model = (
                stamp_model
                or image_model
                or text_model
                or table_model
                or "qwen/qwen3-vl-30b-a3b-instruct"
            )
            logger.info(f"STAMP модель: {stmp_model}")
            stamp_backend = create_ocr_engine(
                "openrouter", api_key=settings.openrouter_api_key, model_name=stmp_model
            )
        else:
            image_backend = create_ocr_engine("dummy")
            stamp_backend = create_ocr_engine("dummy")

        # OCR обработка (двухпроходный алгоритм)
        run_two_pass_ocr(
            job,
            pdf_path,
            blocks,
            crops_dir,
            work_dir,
            strip_backend,
            image_backend,
            stamp_backend,
            start_mem,
        )

        force_gc("после OCR обработки")

        # Генерация результатов (передаём datalab backend для верификации)
        update_job_status(job.id, "processing", progress=0.92, status_message="📄 Генерация результатов...")
        verification_backend = strip_backend if engine == "datalab" else None
        r2_prefix = generate_results(job, pdf_path, blocks, work_dir, verification_backend)

        # Загрузка результатов в R2
        logger.info(f"Загрузка результатов в R2...")
        update_job_status(job.id, "processing", progress=0.95, status_message="☁️ Загрузка в облако...")
        upload_results_to_r2(job, work_dir, r2_prefix)

        # Регистрация OCR результатов в node_files
        if job.node_id:
            update_job_status(job.id, "processing", progress=0.98, status_message="📝 Регистрация файлов...")
            registered_count = register_ocr_results_to_node(job.node_id, job.document_name, work_dir)
            logger.info(f"✅ Зарегистрировано {registered_count} файлов в node_files для node {job.node_id}")

            # Обновляем статус PDF документа
            try:
                from .storage_nodes import update_node_pdf_status

                update_node_pdf_status(job.node_id)
                logger.info(f"PDF status updated for node {job.node_id}")
            except Exception as e:
                logger.warning(f"Failed to update PDF status: {e}")

        update_job_status(job.id, "done", progress=1.0, status_message="✅ Завершено успешно")
        logger.info(f"Задача {job.id} завершена успешно")

        return {"status": "done", "job_id": job_id}

    except Exception as e:
        error_msg = f"{e}\n{traceback.format_exc()}"
        logger.error(f"Ошибка обработки задачи {job_id}: {error_msg}")
        update_job_status(job_id, "error", error_message=str(e), status_message="❌ Ошибка обработки")
        return {"status": "error", "message": str(e)}

    finally:
        # Очистка временной директории
        if work_dir and work_dir.exists():
            try:
                shutil.rmtree(work_dir)
                logger.info(f"✅ Временная директория очищена: {work_dir}")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка очистки временной директории: {e}")

        # Очищаем кэш размеров страниц
        clear_page_size_cache()

        # Финальная сборка мусора
        force_gc("финальная")
        log_memory_delta(f"[END] Задача {job_id}", start_mem)
