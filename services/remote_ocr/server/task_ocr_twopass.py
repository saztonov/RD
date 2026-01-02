"""Двухпроходный OCR алгоритм (экономия памяти)"""
from __future__ import annotations

import logging
from pathlib import Path

from .storage import Job, is_job_paused, update_job_status
from .memory_utils import log_memory_delta
from .pdf_streaming_v2 import pass1_prepare_crops, pass2_ocr_from_manifest, cleanup_manifest_files
from .task_upload import copy_crops_to_final
from .task_helpers import check_paused

logger = logging.getLogger(__name__)


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
    
    logger.info(f"Используется двухпроходный алгоритм (OCR потоков: {settings.ocr_threads_per_job})")
    manifest = None
    
    try:
        # PASS 1: Подготовка кропов на диск
        def on_pass1_progress(current, total):
            progress = 0.1 + 0.3 * (current / total)
            if not is_job_paused(job.id):
                update_job_status(job.id, "processing", progress=progress)
        
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
        def on_pass2_progress(current, total):
            progress = 0.4 + 0.5 * (current / total)
            if not is_job_paused(job.id):
                update_job_status(job.id, "processing", progress=progress)
        
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

