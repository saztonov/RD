"""Вспомогательные функции для OCR задач"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .storage import Job, get_job_file_by_type, get_node_pdf_r2_key, is_job_paused

logger = logging.getLogger(__name__)


def get_r2_storage():
    """Получить R2 Storage клиент (async-обёртка)"""
    from .async_r2_storage import AsyncR2StorageSync

    return AsyncR2StorageSync()


def check_paused(job_id: str) -> bool:
    """Проверить, не поставлена ли задача на паузу"""
    if is_job_paused(job_id):
        logger.info(f"Задача {job_id} поставлена на паузу")
        return True
    return False


def download_job_files(job: Job, work_dir: Path) -> tuple[Path, Path]:
    """Скачать файлы задачи из R2 во временную директорию.

    Если есть node_id - берём из tree_docs/{node_id}/ (через node_files)
    Иначе - из ocr_jobs/{job_id}/ (обратная совместимость)
    """
    r2 = get_r2_storage()

    if job.node_id:
        # Берём PDF из node_files или tree_nodes.attributes
        pdf_r2_key = get_node_pdf_r2_key(job.node_id)
        if not pdf_r2_key:
            raise RuntimeError(f"PDF r2_key not found for node {job.node_id}")

        pdf_path = work_dir / "document.pdf"
        if not r2.download_file(pdf_r2_key, str(pdf_path)):
            raise RuntimeError(f"Failed to download PDF from R2: {pdf_r2_key}")

        # annotation.json берём из job_files (записан при создании задачи)
        blocks_file = get_job_file_by_type(job.id, "blocks")
        if blocks_file:
            blocks_r2_key = blocks_file.r2_key
        else:
            # Fallback: {pdf_parent}/{doc_stem}_annotation.json
            from pathlib import PurePosixPath

            pdf_parent = str(PurePosixPath(pdf_r2_key).parent)
            doc_stem = PurePosixPath(job.document_name).stem
            blocks_r2_key = f"{pdf_parent}/{doc_stem}_annotation.json"

        blocks_path = work_dir / "blocks.json"
        if not r2.download_file(blocks_r2_key, str(blocks_path)):
            raise RuntimeError(
                f"Failed to download annotation from R2: {blocks_r2_key}"
            )
    else:
        # Обратная совместимость: файлы из ocr_jobs
        pdf_file = get_job_file_by_type(job.id, "pdf")
        if not pdf_file:
            raise RuntimeError(f"PDF file not found for job {job.id}")

        pdf_path = work_dir / "document.pdf"
        if not r2.download_file(pdf_file.r2_key, str(pdf_path)):
            raise RuntimeError(f"Failed to download PDF from R2: {pdf_file.r2_key}")

        blocks_file = get_job_file_by_type(job.id, "blocks")
        if not blocks_file:
            raise RuntimeError(f"Blocks file not found for job {job.id}")

        blocks_path = work_dir / "blocks.json"
        if not r2.download_file(blocks_file.r2_key, str(blocks_path)):
            raise RuntimeError(
                f"Failed to download blocks from R2: {blocks_file.r2_key}"
            )

    return pdf_path, blocks_path


def create_empty_result(job: Job, work_dir: Path, pdf_path: Path) -> None:
    """Создать пустой результат"""
    result_json_path = work_dir / "result.json"
    annotation_path = work_dir / "annotation.json"

    import json as json_module

    with open(result_json_path, "w", encoding="utf-8") as f:
        json_module.dump(
            {"doc_name": pdf_path.name, "project_name": "", "blocks": []},
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(annotation_path, "w", encoding="utf-8") as f:
        from rd_core.models import Document

        json.dump(
            Document(pdf_path=pdf_path.name, pages=[]).to_dict(),
            f,
            ensure_ascii=False,
            indent=2,
        )
