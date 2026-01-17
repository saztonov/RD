"""Двухпроходный OCR алгоритм (экономия памяти)"""
from __future__ import annotations

import logging
from pathlib import Path

from .memory_utils import log_memory_delta
from .pdf_streaming_twopass import (
    cleanup_manifest_files,
    pass1_prepare_crops,
    pass2_ocr_from_manifest,
)
from .storage import Job, update_job_status
from .task_upload import copy_crops_to_final

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

    logger.info(
        f"Используется двухпроходный алгоритм (OCR потоков: {settings.ocr_threads_per_job})"
    )
    manifest = None

    # Подготовка информации о блоках для phase_data
    text_blocks = [b for b in blocks if b.get("block_type") == "text"]
    image_blocks_list = [b for b in blocks if b.get("block_type") == "image"]
    stamp_blocks = [b for b in image_blocks_list if b.get("category_code") == "stamp"]
    regular_images = [b for b in image_blocks_list if b.get("category_code") != "stamp"]

    # Состояние обработки блоков
    blocks_status = {b.get("id"): "pending" for b in blocks}

    try:
        # PASS 1: Подготовка кропов на диск
        def on_pass1_progress(current, total):
            progress = 0.1 + 0.3 * (current / total)
            status_msg = f"📦 PASS 1: Подготовка кропов (стр. {current}/{total})"
            phase_data = {
                "current_phase": "pass1",
                "pass1": {"status": "processing", "current": current, "total": total},
                "pass2_strips": {"status": "pending", "total": 0, "processed": 0},
                "pass2_images": {"status": "pending", "total": 0, "processed": 0},
                "blocks_summary": {
                    "total": len(blocks),
                    "text": len(text_blocks),
                    "image": len(regular_images),
                    "stamp": len(stamp_blocks),
                },
            }
            update_job_status(job.id, "processing", progress=progress, status_message=status_msg, phase_data=phase_data)

        manifest = pass1_prepare_crops(
            str(pdf_path),
            blocks,
            str(crops_dir),
            save_image_crops_as_pdf=True,
            on_progress=on_pass1_progress,
        )

        log_memory_delta("После PASS1", start_mem)

        # PASS 2: OCR с загрузкой с диска
        total_strips = len(manifest.strips) if manifest else 0
        total_images = len(manifest.image_blocks) if manifest else 0
        total_requests = total_strips + total_images

        # Подготовка информации о strips и images для phase_data
        strips_info = []
        if manifest and manifest.strips:
            for strip in manifest.strips:
                strips_info.append({
                    "strip_id": strip.strip_id,
                    "block_ids": strip.block_ids,
                    "status": "pending",
                })

        images_info = []
        if manifest and manifest.image_blocks:
            for img in manifest.image_blocks:
                images_info.append({
                    "block_id": img.block_id,
                    "status": "pending",
                    "is_stamp": any(b.get("id") == img.block_id and b.get("category_code") == "stamp" for b in blocks),
                })

        processed_strips = 0
        processed_images = 0

        def on_pass2_progress(current, total, block_info: str = None):
            nonlocal processed_strips, processed_images

            progress = 0.4 + 0.5 * (current / total)
            if block_info:
                status_msg = f"🔍 PASS 2: {block_info} ({current}/{total})"
            else:
                status_msg = f"🔍 PASS 2: Распознавание ({current}/{total})"

            # Определяем что обрабатывается
            current_phase = "pass2_strips"
            if block_info and ("Image" in block_info or "Stamp" in block_info):
                current_phase = "pass2_images"
                processed_images = current - processed_strips
            else:
                processed_strips = current

            # Обновляем статусы в strips_info и images_info
            for i, strip in enumerate(strips_info):
                if i < processed_strips:
                    strip["status"] = "completed"
                elif i == processed_strips and current_phase == "pass2_strips":
                    strip["status"] = "processing"

            for i, img in enumerate(images_info):
                if i < processed_images:
                    img["status"] = "completed"
                elif i == processed_images and current_phase == "pass2_images":
                    img["status"] = "processing"

            phase_data = {
                "current_phase": current_phase,
                "pass1": {"status": "completed", "total": total_strips + total_images, "processed": total_strips + total_images},
                "pass2_strips": {
                    "status": "completed" if processed_strips >= total_strips else "processing",
                    "total": total_strips,
                    "processed": processed_strips,
                    "strips": strips_info,
                },
                "pass2_images": {
                    "status": "processing" if current_phase == "pass2_images" else "pending",
                    "total": total_images,
                    "processed": processed_images,
                    "images": images_info,
                },
                "blocks_summary": {
                    "total": len(blocks),
                    "text": len(text_blocks),
                    "image": len(regular_images),
                    "stamp": len(stamp_blocks),
                },
            }
            update_job_status(job.id, "processing", progress=progress, status_message=status_msg, phase_data=phase_data)

        pass2_ocr_from_manifest(
            manifest,
            blocks,
            strip_backend,
            image_backend,
            stamp_backend,
            str(pdf_path),
            on_progress=on_pass2_progress,
        )

        log_memory_delta("После PASS2", start_mem)

        # Копируем PDF кропы в crops_final
        copy_crops_to_final(work_dir, blocks)

    finally:
        # Очистка временных файлов кропов
        if manifest:
            cleanup_manifest_files(manifest)
