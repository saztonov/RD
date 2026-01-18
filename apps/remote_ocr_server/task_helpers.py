"""Вспомогательные функции для OCR задач"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .storage import Job, get_job_file_by_type, get_node_pdf_r2_key

logger = logging.getLogger(__name__)


def get_r2_storage():
    """Получить R2 Storage клиент (async-обёртка)"""
    from rd_adapters.storage import R2AsyncStorageSync

    return R2AsyncStorageSync.from_env()


def download_job_files(job: Job, work_dir: Path) -> tuple[Path, Path]:
    """Скачать файлы задачи из R2 во временную директорию.

    Новая структура R2: n/{node_id}/
        {doc_name}.pdf
        blocks.json (входные данные для обработки)

    Использует batch download для параллельного скачивания PDF и blocks.
    """
    r2 = get_r2_storage()
    pdf_path = work_dir / "document.pdf"
    blocks_path = work_dir / "blocks.json"

    # node_id обязателен
    if not job.node_id:
        raise RuntimeError(f"node_id is required for job {job.id}")

    # PDF берём из node_files или tree_nodes.attributes
    pdf_r2_key = get_node_pdf_r2_key(job.node_id)
    if not pdf_r2_key:
        raise RuntimeError(f"PDF r2_key not found for node {job.node_id}")

    # blocks.json берём из job_files (записан при создании задачи)
    blocks_file = get_job_file_by_type(job.id, "blocks")
    if not blocks_file:
        raise RuntimeError(f"Blocks file not found for job {job.id}")
    blocks_r2_key = blocks_file.r2_key

    # Параллельное скачивание обоих файлов
    downloads = [
        (pdf_r2_key, str(pdf_path)),
        (blocks_r2_key, str(blocks_path)),
    ]

    logger.info(f"Batch downloading {len(downloads)} files for job {job.id}")
    results = r2.download_files_batch(downloads)

    # Проверяем результаты
    if not results[0]:
        raise RuntimeError(f"Failed to download PDF from R2: {pdf_r2_key}")
    if not results[1]:
        raise RuntimeError(f"Failed to download blocks from R2: {blocks_r2_key}")

    logger.info(f"Successfully downloaded files for job {job.id}")
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
        from rd_domain.models import Document

        json.dump(
            Document(pdf_path=pdf_path.name, pages=[]).to_dict(),
            f,
            ensure_ascii=False,
            indent=2,
        )
