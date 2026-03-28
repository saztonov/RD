"""Pass2 image processing: OCR image blocks с retry, checkpoint и rate limiting."""
from __future__ import annotations

import asyncio
import gc
import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from ..logging_config import get_logger
from ..manifest_models import CropManifestEntry
from ..ocr_constants import make_error
from .pass2_common import (
    CANCELLED_SENTINEL,
    DEADLINE_RESERVE,
    Pass2RuntimeState,
    cancellable_recognize,
    drain_queue,
    save_checkpoint_if_needed,
    should_retry_ocr,
    update_progress,
)

logger = get_logger(__name__)


async def process_image(
    entry: CropManifestEntry,
    *,
    blocks_by_id: Dict,
    image_backend,
    stamp_backend,
    pdf_path: str,
    checkpoint,
    rate_limiter,
    semaphore: asyncio.Semaphore,
    is_paused_fn: Callable[[], bool],
    deadline: Optional[float],
    max_retries: int,
    retry_delays: List[int],
    extract_pdfplumber_text_for_block: Callable,
    fill_image_prompt_variables: Callable,
    inject_pdfplumber_to_ocr_text: Callable,
) -> Optional[Tuple[str, str, int, int]]:
    """Обработка одного IMAGE блока."""
    if is_paused_fn():
        return None

    if deadline and time.time() > deadline - DEADLINE_RESERVE:
        logger.warning(
            f"PASS2 ASYNC: time budget exhausted, пропускаем image {entry.block_id}",
            extra={"event": "pass2_budget_exhausted", "block_id": entry.block_id},
        )
        return None

    if checkpoint.is_image_processed(entry.block_id):
        logger.debug(f"Image {entry.block_id} уже обработан (checkpoint), пропускаем")
        return None

    block = blocks_by_id.get(entry.block_id)
    if not block:
        return None

    block_code = getattr(block, "code", None)
    backend = stamp_backend if block_code == "stamp" else image_backend

    use_pdf = (
        entry.pdf_crop_path
        and entry.total_parts == 1
        and os.path.exists(entry.pdf_crop_path)
        and hasattr(backend, "supports_pdf_input")
        and backend.supports_pdf_input()
    )

    if not use_pdf and not os.path.exists(entry.crop_path):
        logger.warning(f"Image crop не найден: {entry.crop_path}")
        return None

    if is_paused_fn():
        return None

    async with semaphore:
        try:
            pdfplumber_text = await asyncio.to_thread(
                extract_pdfplumber_text_for_block,
                pdf_path,
                block.page_index,
                block.coords_norm,
            )

            category_id = getattr(block, "category_id", None)
            category_code = getattr(block, "category_code", None)

            prompt_data = fill_image_prompt_variables(
                prompt_data=block.prompt,
                doc_name=Path(pdf_path).name,
                page_index=block.page_index,
                block_id=block.id,
                hint=getattr(block, "hint", None),
                pdfplumber_text=pdfplumber_text,
                category_id=category_id,
                category_code=category_code,
                engine=None,
            )

            logger.info(
                f"PASS2 ASYNC: начало обработки IMAGE блока {entry.block_id}",
                extra={
                    "event": "image_ocr_start",
                    "block_id": entry.block_id,
                    "page_index": entry.page_index,
                    "backend_type": type(backend).__name__,
                    "category_code": category_code,
                    "use_pdf_crop": bool(use_pdf),
                },
            )

            text = None
            for img_attempt in range(max_retries + 1):
                if img_attempt > 0:
                    if is_paused_fn():
                        return None
                    delay = retry_delays[min(img_attempt - 1, len(retry_delays) - 1)]
                    logger.warning(
                        f"PASS2 ASYNC: image {entry.block_id} retry "
                        f"{img_attempt}/{max_retries}, ожидание {delay}с"
                    )
                    await asyncio.sleep(delay)

                if not await rate_limiter.acquire_async():
                    logger.warning(f"Image {entry.block_id}: rate limiter timeout")
                    if img_attempt < max_retries:
                        continue
                    return entry.block_id, make_error("rate limiter timeout"), entry.part_idx, entry.total_parts

                try:
                    if use_pdf:
                        logger.info(f"PASS2 ASYNC: используется PDF-кроп для {entry.block_id}")
                        text = await cancellable_recognize(
                            backend, None, prompt_data, None, entry.pdf_crop_path,
                            is_paused_fn=is_paused_fn,
                        )
                    else:
                        crop = await asyncio.to_thread(Image.open, entry.crop_path)
                        try:
                            text = await cancellable_recognize(
                                backend, crop, prompt_data,
                                is_paused_fn=is_paused_fn,
                            )
                        finally:
                            crop.close()
                    if text is CANCELLED_SENTINEL:
                        return None
                except Exception as ocr_err:
                    text = make_error(str(ocr_err))
                finally:
                    await rate_limiter.release_async()

                if not should_retry_ocr(text, f"image {entry.block_id}", img_attempt, max_retries):
                    break

            logger.info(
                f"PASS2 ASYNC: завершена обработка IMAGE блока {entry.block_id}",
                extra={
                    "event": "image_ocr_completed",
                    "block_id": entry.block_id,
                    "page_index": entry.page_index,
                    "response_length": len(text) if text else 0,
                    "backend_type": type(backend).__name__,
                    "category_code": category_code,
                    "use_pdf_crop": bool(use_pdf),
                },
            )

            text = inject_pdfplumber_to_ocr_text(text, pdfplumber_text)
            block.pdfplumber_text = pdfplumber_text

            return entry.block_id, text, entry.part_idx, entry.total_parts

        except Exception as e:
            logger.error(
                f"PASS2 ASYNC: image processing error {entry.block_id}",
                extra={
                    "event": "pass2_image_error",
                    "block_id": entry.block_id,
                    "page_index": entry.page_index,
                    "block_type": entry.block_type,
                    "backend": type(backend).__name__,
                    "use_pdf_crop": use_pdf,
                },
                exc_info=True,
            )
            return entry.block_id, make_error(str(e)), entry.part_idx, entry.total_parts


async def run_image_phase(
    manifest_images: List[CropManifestEntry],
    *,
    blocks_by_id: Dict,
    image_backend,
    stamp_backend,
    pdf_path: str,
    checkpoint,
    rate_limiter,
    max_workers: int,
    is_paused_fn: Callable[[], bool],
    deadline: Optional[float],
    max_retries: int,
    retry_delays: List[int],
    state: Pass2RuntimeState,
    total_requests: int,
    on_progress: Optional[Callable],
    checkpoint_path,
    extract_pdfplumber_text_for_block: Callable,
    fill_image_prompt_variables: Callable,
    inject_pdfplumber_to_ocr_text: Callable,
) -> Tuple[Dict[str, Dict[int, str]], Dict[str, int]]:
    """Обработать все image блоки и вернуть (image_block_parts, image_block_total_parts)."""
    semaphore = asyncio.Semaphore(max_workers)
    image_block_parts: Dict[str, Dict[int, str]] = {}
    image_block_total_parts: Dict[str, int] = {}

    image_queue: asyncio.Queue = asyncio.Queue()
    for entry in manifest_images:
        image_queue.put_nowait(entry)

    async def _image_worker():
        while not image_queue.empty():
            if is_paused_fn():
                drain_queue(image_queue)
                return
            try:
                entry = image_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            try:
                result = await process_image(
                    entry,
                    blocks_by_id=blocks_by_id,
                    image_backend=image_backend,
                    stamp_backend=stamp_backend,
                    pdf_path=pdf_path,
                    checkpoint=checkpoint,
                    rate_limiter=rate_limiter,
                    semaphore=semaphore,
                    is_paused_fn=is_paused_fn,
                    deadline=deadline,
                    max_retries=max_retries,
                    retry_delays=retry_delays,
                    extract_pdfplumber_text_for_block=extract_pdfplumber_text_for_block,
                    fill_image_prompt_variables=fill_image_prompt_variables,
                    inject_pdfplumber_to_ocr_text=inject_pdfplumber_to_ocr_text,
                )
            except Exception as exc:
                logger.error(f"PASS2 ASYNC: image exception: {exc}", exc_info=True)
                await update_progress(state, total_requests, on_progress, "Image (error)")
                image_queue.task_done()
                continue

            if result:
                block_id, text, part_idx, total_parts = result

                if block_id not in image_block_parts:
                    image_block_parts[block_id] = {}
                    image_block_total_parts[block_id] = total_parts
                image_block_parts[block_id][part_idx] = text

                checkpoint.mark_image_processed(block_id, text, part_idx, total_parts)
                await save_checkpoint_if_needed(state, checkpoint, checkpoint_path)

                block = blocks_by_id.get(block_id)
                if block:
                    page_num = block.page_index + 1
                    category = getattr(block, "category_code", None) or "image"
                    block_info = f"Image: {category} (стр. {page_num})"
                else:
                    block_info = "Image"
                await update_progress(state, total_requests, on_progress, block_info)
            else:
                await update_progress(state, total_requests, on_progress, "Image")

            gc.collect()
            image_queue.task_done()

    workers = [asyncio.create_task(_image_worker()) for _ in range(max_workers)]
    await asyncio.gather(*workers)

    return image_block_parts, image_block_total_parts
