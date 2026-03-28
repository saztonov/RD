"""Pass2 strip processing: OCR strips с retry, checkpoint и rate limiting."""
from __future__ import annotations

import asyncio
import gc
import os
import time
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from ..logging_config import get_logger
from ..manifest_models import StripManifestEntry
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


async def process_strip(
    strip: StripManifestEntry,
    strip_idx: int,
    *,
    blocks_by_id: Dict,
    strip_backend,
    checkpoint,
    rate_limiter,
    semaphore: asyncio.Semaphore,
    is_paused_fn: Callable[[], bool],
    deadline: Optional[float],
    max_retries: int,
    retry_delays: List[int],
    build_strip_prompt: Callable,
    parse_batch_response_by_index: Callable,
) -> Optional[Tuple[StripManifestEntry, Dict[int, str], int]]:
    """Обработка одного strip."""
    if is_paused_fn():
        return None

    if deadline and time.time() > deadline - DEADLINE_RESERVE:
        logger.warning(
            f"PASS2 ASYNC: time budget exhausted, пропускаем strip {strip.strip_id}",
            extra={"event": "pass2_budget_exhausted", "strip_id": strip.strip_id},
        )
        return None

    if checkpoint.is_strip_processed(strip.strip_id):
        logger.debug(f"Strip {strip.strip_id} уже обработан (checkpoint), пропускаем")
        return None

    if not strip.strip_path or not os.path.exists(strip.strip_path):
        logger.warning(f"Strip {strip.strip_id} не найден: {strip.strip_path}")
        return None

    if is_paused_fn():
        return None

    async with semaphore:
        try:
            strip_blocks = [
                blocks_by_id[bp["block_id"]]
                for bp in strip.block_parts
                if bp["block_id"] in blocks_by_id
            ]

            if not strip_blocks:
                return None

            prompt_data = build_strip_prompt(strip_blocks)

            block_ids = [bp["block_id"] for bp in strip.block_parts]
            logger.info(
                f"PASS2 ASYNC: начало обработки strip {strip.strip_id} "
                f"({len(strip.block_parts)} блоков): {block_ids}",
                extra={
                    "event": "strip_ocr_start",
                    "strip_id": strip.strip_id,
                    "block_count": len(strip.block_parts),
                    "block_ids": block_ids,
                },
            )

            response_text = None
            for strip_attempt in range(max_retries + 1):
                if strip_attempt > 0:
                    if is_paused_fn():
                        return None
                    delay = retry_delays[min(strip_attempt - 1, len(retry_delays) - 1)]
                    logger.warning(
                        f"PASS2 ASYNC: strip {strip.strip_id} retry "
                        f"{strip_attempt}/{max_retries}, ожидание {delay}с"
                    )
                    await asyncio.sleep(delay)

                merged_image = await asyncio.to_thread(Image.open, strip.strip_path)

                try:
                    if not await rate_limiter.acquire_async():
                        logger.warning(f"Strip {strip.strip_id}: rate limiter timeout")
                        merged_image.close()
                        if strip_attempt < max_retries:
                            continue
                        error_results = {i: make_error("rate limiter timeout") for i in range(len(strip.block_parts))}
                        return strip, error_results, strip_idx

                    try:
                        response_text = await cancellable_recognize(
                            strip_backend, merged_image, prompt_data,
                            is_paused_fn=is_paused_fn,
                        )
                        if response_text is CANCELLED_SENTINEL:
                            return None
                    finally:
                        await rate_limiter.release_async()
                finally:
                    merged_image.close()

                if not should_retry_ocr(response_text, f"strip {strip.strip_id}", strip_attempt, max_retries):
                    break

            response_len = len(response_text) if response_text else 0
            if response_len == 0:
                logger.warning(
                    f"PASS2 ASYNC: strip {strip.strip_id} — пустой ответ от OCR бэкенда",
                    extra={
                        "event": "strip_ocr_empty",
                        "strip_id": strip.strip_id,
                        "block_count": len(strip.block_parts),
                        "backend_type": type(strip_backend).__name__,
                    },
                )
            else:
                logger.info(
                    f"PASS2 ASYNC: завершена обработка strip {strip.strip_id}, "
                    f"ответ {response_len} символов",
                    extra={
                        "event": "strip_ocr_completed",
                        "strip_id": strip.strip_id,
                        "response_length": response_len,
                        "block_count": len(strip.block_parts),
                        "strip_attempt": strip_attempt,
                        "backend_type": type(strip_backend).__name__,
                    },
                )

            index_results = parse_batch_response_by_index(
                len(strip.block_parts), response_text, block_ids=block_ids
            )

            return strip, index_results, strip_idx

        except Exception as e:
            logger.error(
                f"PASS2 ASYNC: strip processing error {strip.strip_id}",
                extra={
                    "event": "pass2_strip_error",
                    "strip_id": strip.strip_id,
                    "block_ids": [bp["block_id"] for bp in strip.block_parts],
                    "block_count": len(strip.block_parts),
                },
                exc_info=True,
            )
            error_results = {i: make_error(str(e)) for i in range(len(strip.block_parts))}
            return strip, error_results, strip_idx


async def run_strip_phase(
    manifest_strips: List[StripManifestEntry],
    *,
    blocks_by_id: Dict,
    strip_backend,
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
    build_strip_prompt: Callable,
    parse_batch_response_by_index: Callable,
) -> Tuple[Dict[str, Dict[int, str]], Dict[str, int]]:
    """Обработать все strips и вернуть (text_block_parts, text_block_total_parts)."""
    semaphore = asyncio.Semaphore(max_workers)
    text_block_parts: Dict[str, Dict[int, str]] = {}
    text_block_total_parts: Dict[str, int] = {}

    strip_queue: asyncio.Queue = asyncio.Queue()
    for idx, strip in enumerate(manifest_strips):
        strip_queue.put_nowait((strip, idx))

    async def _strip_worker():
        while not strip_queue.empty():
            if is_paused_fn():
                drain_queue(strip_queue)
                return
            try:
                strip, idx = strip_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            try:
                try:
                    result = await process_strip(
                        strip, idx,
                        blocks_by_id=blocks_by_id,
                        strip_backend=strip_backend,
                        checkpoint=checkpoint,
                        rate_limiter=rate_limiter,
                        semaphore=semaphore,
                        is_paused_fn=is_paused_fn,
                        deadline=deadline,
                        max_retries=max_retries,
                        retry_delays=retry_delays,
                        build_strip_prompt=build_strip_prompt,
                        parse_batch_response_by_index=parse_batch_response_by_index,
                    )
                except Exception as exc:
                    logger.error(f"PASS2 ASYNC: strip exception: {exc}", exc_info=True)
                    await update_progress(state, total_requests, on_progress, "Strip (error)")
                    continue

                if result:
                    strip_obj, index_results, _ = result
                    block_results = {}
                    for i, bp in enumerate(strip_obj.block_parts):
                        block_id = bp["block_id"]
                        part_idx = bp["part_idx"]
                        total_parts = bp["total_parts"]
                        text = index_results.get(i, "")

                        if block_id not in text_block_parts:
                            text_block_parts[block_id] = {}
                            text_block_total_parts[block_id] = total_parts
                        text_block_parts[block_id][part_idx] = text
                        block_results[block_id] = text

                    checkpoint.mark_strip_processed(strip_obj.strip_id, block_results)
                    await save_checkpoint_if_needed(state, checkpoint, checkpoint_path)

                    num_blocks = len(strip_obj.block_parts)
                    if num_blocks == 1:
                        suffix = ""
                    elif num_blocks < 5:
                        suffix = "а"
                    else:
                        suffix = "ов"
                    await update_progress(state, total_requests, on_progress, f"Strip ({num_blocks} блок{suffix})")
                else:
                    await update_progress(state, total_requests, on_progress, "Strip")

                gc.collect()
            finally:
                strip_queue.task_done()

    workers = [asyncio.create_task(_strip_worker()) for _ in range(max_workers)]
    await asyncio.gather(*workers)

    return text_block_parts, text_block_total_parts
