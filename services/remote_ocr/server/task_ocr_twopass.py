"""Двухпроходный OCR алгоритм (экономия памяти)"""
from __future__ import annotations

import asyncio
from pathlib import Path

from .checkpoint_models import OCRCheckpoint, get_checkpoint_path
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


# Флаг для включения async режима (можно переключать через settings)
USE_ASYNC_PASS2 = True

# Флаг для включения checkpoint (можно переключать)
USE_CHECKPOINT = True


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
    engine: str = "openrouter",
):
    """Двухпроходный алгоритм OCR (экономия памяти)"""
    from .settings import settings

    logger.info(
        f"Используется двухпроходный алгоритм (OCR потоков: {settings.ocr_threads_per_job})"
    )
    manifest = None
    updater = get_debounced_updater(job.id)
    checkpoint = None

    # Загрузка checkpoint для resume
    if USE_CHECKPOINT:
        checkpoint_path = get_checkpoint_path(work_dir)
        checkpoint = OCRCheckpoint.load(checkpoint_path)
        if checkpoint:
            logger.info(
                f"Checkpoint загружен: phase={checkpoint.phase}, "
                f"strips={len(checkpoint.processed_strips)}, "
                f"images={len(checkpoint.processed_images)}"
            )
        else:
            logger.info("Checkpoint не найден, начинаем с начала")

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

        # Создаём или обновляем checkpoint
        if USE_CHECKPOINT and checkpoint is None:
            checkpoint = OCRCheckpoint.create_new(
                job_id=job.id,
                total_strips=total_strips,
                total_images=total_images,
                manifest_path=str(crops_dir / "manifest.json") if crops_dir else None,
            )
        elif USE_CHECKPOINT and checkpoint:
            checkpoint.total_strips = total_strips
            checkpoint.total_images = total_images

        # Выбор между async и sync режимом
        if USE_ASYNC_PASS2:
            from .pdf_twopass.pass2_ocr_async import pass2_ocr_from_manifest_async

            logger.info("PASS2: используется async режим (asyncio.gather)")

            # Для Chandra: последовательная обработка (LM Studio однопоточная)
            max_concurrent = 1 if engine == "chandra" else None

            # Запуск async pass2 через asyncio.run
            asyncio.run(
                pass2_ocr_from_manifest_async(
                    manifest,
                    blocks,
                    strip_backend,
                    image_backend,
                    stamp_backend,
                    str(pdf_path),
                    on_progress=on_pass2_progress,
                    check_paused=lambda: is_job_paused(job.id),
                    max_concurrent=max_concurrent,
                    checkpoint=checkpoint if USE_CHECKPOINT else None,
                    work_dir=work_dir if USE_CHECKPOINT else None,
                )
            )
        else:
            logger.info("PASS2: используется sync режим (ThreadPoolExecutor)")
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

        # Удаляем checkpoint после успешного завершения
        if USE_CHECKPOINT:
            checkpoint_path = get_checkpoint_path(work_dir)
            if checkpoint_path.exists():
                checkpoint_path.unlink()
                logger.info("Checkpoint удалён после успешного завершения")

    finally:
        # Очистка временных файлов кропов
        if manifest:
            cleanup_manifest_files(manifest)
