"""Регистрация OCR результатов в node_files"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Dict, List

from services.remote_ocr.server.node_storage.file_manager import (
    add_node_file,
    get_node_pdf_r2_key,
)
from services.remote_ocr.server.storage_client import get_client

logger = logging.getLogger(__name__)


def _delete_old_ocr_entries(node_id: str) -> int:
    """Удалить старые записи OCR результатов из node_files (кроме pdf)."""
    client = get_client()
    ocr_file_types = ["result_json", "annotation", "ocr_html", "result_md", "crop", "crops_folder"]

    try:
        result = client.table("node_files").delete().eq("node_id", node_id).in_(
            "file_type", ocr_file_types
        ).execute()
        deleted_count = len(result.data) if result.data else 0
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old OCR entries for node {node_id}")
        return deleted_count
    except Exception as e:
        logger.warning(f"Failed to delete old OCR entries: {e}")
        return 0


def _write_latest_ocr_run(node_id: str, job_id: str, files_info: Dict[str, str]) -> bool:
    """Записать latest_ocr_run.json в R2."""
    try:
        from services.remote_ocr.server.task_helpers import get_r2_storage

        r2 = get_r2_storage()
        now = datetime.utcnow().isoformat() + "Z"

        latest_run = {
            "job_id": job_id,
            "created_at": now,
            "files": files_info
        }

        latest_key = f"tree_docs/{node_id}/latest_ocr_run.json"
        content = json.dumps(latest_run, ensure_ascii=False, indent=2)
        r2.upload_text(content, latest_key, content_type="application/json")

        logger.info(f"Written latest_ocr_run.json to {latest_key}")
        return True
    except Exception as e:
        logger.error(f"Failed to write latest_ocr_run.json: {e}")
        return False


def register_ocr_results_to_node(node_id: str, job_id: str, doc_name: str, work_dir) -> int:
    """Зарегистрировать все OCR результаты в node_files.

    Файлы загружены в изолированную папку задачи:
      tree_docs/{node_id}/ocr_runs/{job_id}/

    Удаляет старые записи OCR из node_files и записывает latest_ocr_run.json.
    Кропы сохраняются с метаданными блоков (block_id, page_index, coords, block_type).
    """
    if not node_id:
        return 0

    work_path = Path(work_dir)
    now = datetime.utcnow().isoformat()

    # Изолированная папка для этой задачи
    job_r2_prefix = f"tree_docs/{node_id}/ocr_runs/{job_id}"

    # Удаляем старые OCR записи из node_files (кроме pdf)
    _delete_old_ocr_entries(node_id)

    registered = 0
    files_info: Dict[str, str] = {}

    # Загружаем annotation.json для получения метаданных блоков
    blocks_by_id: Dict[str, dict] = {}
    annotation_path = work_path / "annotation.json"
    if annotation_path.exists():
        try:
            with open(annotation_path, "r", encoding="utf-8") as f:
                ann = json.load(f)
            for page in ann.get("pages", []):
                for blk in page.get("blocks", []):
                    blocks_by_id[blk["id"]] = blk
        except Exception as e:
            logger.warning(f"Failed to load annotation.json for metadata: {e}")

    # result.json (упрощённое имя в изолированной папке)
    result_json = work_path / "result.json"
    if result_json.exists():
        r2_key = f"{job_r2_prefix}/result.json"
        files_info["result"] = f"ocr_runs/{job_id}/result.json"
        add_node_file(
            node_id,
            "result_json",
            r2_key,
            "result.json",
            result_json.stat().st_size,
            "application/json",
            metadata={"ocr_run_id": job_id},
        )
        registered += 1

    # annotation.json
    if annotation_path.exists():
        r2_key = f"{job_r2_prefix}/annotation.json"
        files_info["annotation"] = f"ocr_runs/{job_id}/annotation.json"
        add_node_file(
            node_id,
            "annotation",
            r2_key,
            "annotation.json",
            annotation_path.stat().st_size,
            "application/json",
            metadata={"ocr_run_id": job_id},
        )
        registered += 1

    # ocr.html
    ocr_html = work_path / "ocr_result.html"
    if ocr_html.exists():
        r2_key = f"{job_r2_prefix}/ocr.html"
        files_info["ocr_html"] = f"ocr_runs/{job_id}/ocr.html"
        add_node_file(
            node_id,
            "ocr_html",
            r2_key,
            "ocr.html",
            ocr_html.stat().st_size,
            "text/html",
            metadata={"ocr_run_id": job_id},
        )
        registered += 1

    # document.md
    document_md = work_path / "document.md"
    if document_md.exists():
        r2_key = f"{job_r2_prefix}/document.md"
        files_info["document_md"] = f"ocr_runs/{job_id}/document.md"
        add_node_file(
            node_id,
            "result_md",
            r2_key,
            "document.md",
            document_md.stat().st_size,
            "text/markdown",
            metadata={"ocr_run_id": job_id},
        )
        registered += 1
        logger.info(f"✅ Зарегистрирован document.md в node_files (file_type=result_md)")
    else:
        logger.warning(f"⚠️ document.md не найден для регистрации: {document_md}")

    # Собираем все кропы из crops/ и crops_final/
    all_crop_files: List[Path] = []
    for crops_subdir in ["crops", "crops_final"]:
        crops_dir = work_path / crops_subdir
        if crops_dir.exists():
            for crop_file in crops_dir.iterdir():
                if crop_file.is_file() and crop_file.suffix.lower() == ".pdf":
                    # Избегаем дубликатов (проверяем по имени файла)
                    if not any(c.name == crop_file.name for c in all_crop_files):
                        all_crop_files.append(crop_file)

    # Регистрируем папку кропов как сущность
    if all_crop_files:
        r2_key = f"{job_r2_prefix}/crops/"
        files_info["crops"] = f"ocr_runs/{job_id}/crops/"
        add_node_file(
            node_id,
            "crops_folder",
            r2_key,
            "crops",
            0,
            "inode/directory",
            metadata={"crops_count": len(all_crop_files), "created_at": now, "ocr_run_id": job_id},
        )
        registered += 1

    # Регистрируем каждый кроп с метаданными блока
    for crop_file in all_crop_files:
        block_id = crop_file.stem  # block_id = имя файла без расширения
        block_data = blocks_by_id.get(block_id, {})

        add_node_file(
            node_id,
            "crop",
            f"{job_r2_prefix}/crops/{crop_file.name}",
            crop_file.name,
            crop_file.stat().st_size,
            "application/pdf",
            metadata={
                "block_id": block_id,
                "page_index": block_data.get("page_index"),
                "coords_norm": block_data.get("coords_norm"),
                "block_type": block_data.get("block_type"),
                "ocr_run_id": job_id,
            },
        )
        registered += 1

    # Записываем latest_ocr_run.json в R2
    _write_latest_ocr_run(node_id, job_id, files_info)

    logger.info(
        f"Registered {registered} OCR result files for node {node_id}, job {job_id} ({len(all_crop_files)} crops)"
    )
    return registered


def update_node_pdf_status(node_id: str):
    """
    Обновить статус PDF документа в БД

    Args:
        node_id: ID узла документа
    """
    # Добавляем корневую директорию проекта в путь если ещё не добавлено
    project_root = Path(__file__).parent.parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        import httpx

        from rd_core.pdf_status import calculate_pdf_status
        from rd_core.r2_storage import R2Storage

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")

        if not supabase_url or not supabase_key:
            logger.error("SUPABASE_URL or SUPABASE_KEY not set")
            return

        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
        }

        # Получаем узел
        response = httpx.get(
            f"{supabase_url}/rest/v1/tree_nodes",
            params={"id": f"eq.{node_id}", "select": "id,attributes"},
            headers=headers,
            timeout=10.0,
        )
        response.raise_for_status()
        nodes = response.json()

        if not nodes:
            logger.warning(f"Node {node_id} not found")
            return

        r2_key = nodes[0].get("attributes", {}).get("r2_key", "")
        if not r2_key:
            logger.warning(f"Node {node_id} has no r2_key")
            return

        # Вычисляем статус
        r2 = R2Storage()
        status, message = calculate_pdf_status(r2, node_id, r2_key, check_blocks=True)

        # Обновляем в БД
        rpc_response = httpx.post(
            f"{supabase_url}/rest/v1/rpc/update_pdf_status",
            json={"p_node_id": node_id, "p_status": status.value, "p_message": message},
            headers=headers,
            timeout=10.0,
        )
        rpc_response.raise_for_status()

        logger.info(f"Updated PDF status for {node_id}: {status.value}")

    except Exception as e:
        logger.error(f"Failed to update node PDF status: {e}")
        raise
