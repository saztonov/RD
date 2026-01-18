"""Двухпроходный OCR алгоритм (экономия памяти)"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from rd_pipeline.utils.memory import log_memory_delta
from .pdf_streaming_twopass import (
    cleanup_manifest_files,
    pass1_prepare_crops,
    pass2_ocr_from_manifest,
)
from .storage import Job, update_job_status
from .task_upload import copy_crops_to_final

logger = logging.getLogger(__name__)


def _save_text_block_outputs(work_dir: Path, blocks: list, manifest) -> None:
    """Save text blocks for UI inspection."""
    if not manifest:
        return

    from rd_domain.models.enums import BlockType

    text_blocks_list = [b for b in blocks if b.block_type == BlockType.TEXT]
    if not text_blocks_list:
        return

    text_dir = work_dir / "text_block"
    text_dir.mkdir(parents=True, exist_ok=True)

    block_entries = []
    for block in text_blocks_list:
        block_dict = block.to_dict()
        block_entries.append(block_dict)

    blocks_payload = {"blocks": block_entries}
    blocks_path = text_dir / "blocks.json"
    with open(blocks_path, "w", encoding="utf-8") as f:
        json.dump(blocks_payload, f, ensure_ascii=False, indent=2)

    logger.info("Saved text_block outputs: %s blocks", len(block_entries))


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
    from rd_domain.models.enums import BlockType
    text_blocks = [b for b in blocks if b.block_type == BlockType.TEXT]
    image_blocks_list = [b for b in blocks if b.block_type == BlockType.IMAGE]
    stamp_blocks = [b for b in image_blocks_list if b.category_code == "stamp"]
    regular_images = [b for b in image_blocks_list if b.category_code != "stamp"]

    # Состояние обработки блоков
    blocks_status = {b.id: "pending" for b in blocks}

    try:
        # PASS 1: Подготовка кропов на диск
        def on_pass1_progress(current, total):
            progress = 0.1 + 0.3 * (current / total)
            status_msg = f"📦 PASS 1: Подготовка кропов (стр. {current}/{total})"
            phase_data = {
                "current_phase": "pass1",
                "pass1": {"status": "processing", "current": current, "total": total},
                "pass2_text": {"status": "pending", "total": 0, "processed": 0},
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
        total_text_blocks = len(manifest.text_blocks) if manifest else 0
        total_images = len(manifest.image_blocks) if manifest else 0
        total_requests = total_text_blocks + total_images

        # Подготовка информации о text_blocks и images для phase_data
        text_blocks_info = []
        if manifest and manifest.text_blocks:
            for tb in manifest.text_blocks:
                text_blocks_info.append({
                    "block_id": tb.block_id,
                    "status": "pending",
                })

        images_info = []
        if manifest and manifest.image_blocks:
            for img in manifest.image_blocks:
                images_info.append({
                    "block_id": img.block_id,
                    "status": "pending",
                    "is_stamp": any(b.id == img.block_id and b.category_code == "stamp" for b in blocks),
                })

        processed_text_blocks = 0
        processed_images = 0

        phase_data = {
            "current_phase": "pass2_text" if total_text_blocks else "pass2_images",
            "pass1": {
                "status": "completed",
                "total": total_text_blocks + total_images,
                "processed": total_text_blocks + total_images,
            },
            "pass2_text": {
                "status": "pending",
                "total": total_text_blocks,
                "processed": processed_text_blocks,
                "blocks": text_blocks_info,
            },
            "pass2_images": {
                "status": "pending",
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
        update_job_status(
            job.id,
            "processing",
            progress=0.4,
            status_message="PASS 2: Pending",
            phase_data=phase_data,
        )

        def on_pass2_progress(current, total, block_info: str = None):
            nonlocal processed_text_blocks, processed_images

            progress = 0.4 + 0.5 * (current / total)
            if block_info:
                status_msg = f"🔍 PASS 2: {block_info} ({current}/{total})"
            else:
                status_msg = f"🔍 PASS 2: Распознавание ({current}/{total})"

            # Определяем что обрабатывается
            current_phase = "pass2_text"
            if block_info and ("Image" in block_info or "Stamp" in block_info):
                current_phase = "pass2_images"
                processed_images = current - processed_text_blocks
            else:
                processed_text_blocks = current

            # Обновляем статусы в text_blocks_info и images_info
            for i, tb in enumerate(text_blocks_info):
                if i < processed_text_blocks:
                    tb["status"] = "completed"
                elif i == processed_text_blocks and current_phase == "pass2_text":
                    tb["status"] = "processing"

            for i, img in enumerate(images_info):
                if i < processed_images:
                    img["status"] = "completed"
                elif i == processed_images and current_phase == "pass2_images":
                    img["status"] = "processing"

            phase_data = {
                "current_phase": current_phase,
                "pass1": {"status": "completed", "total": total_text_blocks + total_images, "processed": total_text_blocks + total_images},
                "pass2_text": {
                    "status": "completed" if processed_text_blocks >= total_text_blocks else "processing",
                    "total": total_text_blocks,
                    "processed": processed_text_blocks,
                    "blocks": text_blocks_info,
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
        _save_text_block_outputs(work_dir, blocks, manifest)

    finally:
        # Очистка временных файлов кропов
        if manifest:
            cleanup_manifest_files(manifest)
