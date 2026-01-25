"""Двухпроходный OCR алгоритм (экономия памяти)"""
from __future__ import annotations

from pathlib import Path

from .debounced_updater import get_debounced_updater
from .logging_config import get_logger
from .memory_utils import log_memory_delta
from .pdf_streaming_twopass import (
    cleanup_manifest_files,
    pass1_prepare_crops,
    pass2_ocr_from_manifest,
)
from .storage import Job, is_job_paused
from .task_helpers import check_paused
from .task_upload import copy_crops_to_final

logger = get_logger(__name__)


def run_two_pass_ocr(
    job: Job,
    pdf_path: Path,
    blocks: list,
    crops_dir: Path,
    work_dir: Path,
    strip_backend,
    image_backend,
    stamp_backend,
    start_mem: float,
):
    """Двухпроходный алгоритм OCR (экономия памяти)"""
    from .settings import settings

    logger.info(
        f"Используется двухпроходный алгоритм (OCR потоков: {settings.ocr_threads_per_job})"
    )
    manifest = None
    updater = get_debounced_updater(job.id)

    try:
        # PASS 1: Подготовка кропов на диск
        def on_pass1_progress(current, total):
            progress = 0.1 + 0.3 * (current / total)
            status_msg = f"📦 PASS 1: Подготовка кропов (стр. {current}/{total})"
            if not is_job_paused(job.id):
                updater.update("processing", progress=progress, status_message=status_msg)

        manifest = pass1_prepare_crops(
            str(pdf_path),
            blocks,
            str(crops_dir),
            save_image_crops_as_pdf=True,
            on_progress=on_pass1_progress,
        )

        log_memory_delta("После PASS1", start_mem)

        if check_paused(job.id):
            return

        # PASS 2: OCR с загрузкой с диска
        total_strips = len(manifest.strips) if manifest else 0
        total_images = len(manifest.image_blocks) if manifest else 0
        total_requests = total_strips + total_images

        def on_pass2_progress(current, total, block_info: str = None):
            progress = 0.4 + 0.5 * (current / total)
            if block_info:
                status_msg = f"🔍 PASS 2: {block_info} ({current}/{total})"
            else:
                status_msg = f"🔍 PASS 2: Распознавание ({current}/{total})"
            if not is_job_paused(job.id):
                updater.update("processing", progress=progress, status_message=status_msg)

        pass2_ocr_from_manifest(
            manifest,
            blocks,
            strip_backend,
            image_backend,
            stamp_backend,
            str(pdf_path),
            on_progress=on_pass2_progress,
            check_paused=lambda: is_job_paused(job.id),
        )

        log_memory_delta("После PASS2", start_mem)

        # Копируем PDF кропы в crops_final
        copy_crops_to_final(work_dir, blocks)

    finally:
        # Очистка временных файлов кропов
        if manifest:
            cleanup_manifest_files(manifest)
