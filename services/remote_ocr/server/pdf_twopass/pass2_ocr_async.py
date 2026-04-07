"""
PASS 2 ASYNC: Асинхронный OCR с использованием asyncio.gather.

Публичная точка входа: pass2_ocr_from_manifest_async и pass2_ocr_from_manifest_sync_wrapper.
Orchestration двух фаз (strips + images) и финальный checkpoint-save.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, List, Optional

from ..checkpoint_models import OCRCheckpoint, get_checkpoint_path
from ..logging_config import get_logger
from ..manifest_models import TwoPassManifest
from ..memory_utils import force_gc, log_memory, log_memory_delta
from ..rate_limiter import get_unified_async_limiter
from ..settings import settings

from .pass2_common import Pass2RuntimeState, get_retry_params, make_pause_checker
from .pass2_images import run_image_phase
from .pass2_strips import run_strip_phase

logger = get_logger(__name__)


async def pass2_ocr_from_manifest_async(
    manifest: TwoPassManifest,
    blocks: List,
    strip_backend,
    image_backend,
    stamp_backend,
    pdf_path: str,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    check_paused: Optional[Callable[[], bool]] = None,
    max_concurrent: Optional[int] = None,
    checkpoint: Optional[OCRCheckpoint] = None,
    work_dir: Optional[Path] = None,
    deadline: Optional[float] = None,
    text_fallback_backend=None,
) -> None:
    """
    PASS 2 ASYNC: Асинхронный OCR с загрузкой кропов с диска.

    Поддерживает checkpoint/resume для возможности продолжения после паузы.
    """
    from ..worker_pdf import extract_pdfplumber_text_for_block
    from ..worker_prompts import (
        build_strip_prompt,
        fill_image_prompt_variables,
        inject_pdfplumber_to_ocr_text,
        parse_batch_response_by_index,
    )

    start_mem = log_memory("PASS2 ASYNC start")

    total_requests = len(manifest.strips) + len(manifest.image_blocks)
    blocks_by_id = {b.id: b for b in blocks}

    # Инициализация или восстановление checkpoint
    if checkpoint is None:
        checkpoint = OCRCheckpoint.create_new(
            job_id="unknown",
            total_strips=len(manifest.strips),
            total_images=len(manifest.image_blocks),
        )
    else:
        restored = checkpoint.apply_to_blocks(blocks)
        if restored > 0:
            logger.info(
                f"PASS2 ASYNC: восстановлено {restored} блоков из checkpoint",
                extra={
                    "event": "checkpoint_restored",
                    "checkpoint_count": restored,
                    "phase": checkpoint.phase,
                },
            )

    # Shared state
    state = Pass2RuntimeState(
        processed=len(checkpoint.processed_strips) + len(checkpoint.processed_images),
    )

    rate_limiter = get_unified_async_limiter()
    checkpoint_path = get_checkpoint_path(work_dir) if work_dir else None
    is_paused_fn = make_pause_checker(check_paused)
    max_workers = max_concurrent or settings.ocr_threads_per_job

    # Retry params
    strip_max_retries, strip_retry_delays, _ = get_retry_params(type(strip_backend).__name__)
    image_max_retries, image_retry_delays, _ = get_retry_params(type(image_backend).__name__)

    # ═══ PHASE 1: STRIPS ═══
    checkpoint.phase = "pass2_strips"
    logger.info(
        f"PASS2 ASYNC: обработка {len(manifest.strips)} strips "
        f"({max_workers} workers, bounded queue)"
    )

    failover_enabled = bool(
        text_fallback_backend is not None
        and getattr(settings, "chandra_failover_to_fallback", False)
        and type(strip_backend).__name__ == "ChandraBackend"
    )
    if failover_enabled:
        logger.info(
            f"PASS2 ASYNC: early failover включён "
            f"(primary={type(strip_backend).__name__}, "
            f"fallback={type(text_fallback_backend).__name__})"
        )

    text_block_parts, text_block_total_parts = await run_strip_phase(
        manifest.strips,
        blocks_by_id=blocks_by_id,
        strip_backend=strip_backend,
        checkpoint=checkpoint,
        rate_limiter=rate_limiter,
        max_workers=max_workers,
        is_paused_fn=is_paused_fn,
        deadline=deadline,
        max_retries=strip_max_retries,
        retry_delays=strip_retry_delays,
        state=state,
        total_requests=total_requests,
        on_progress=on_progress,
        checkpoint_path=checkpoint_path,
        build_strip_prompt=build_strip_prompt,
        parse_batch_response_by_index=parse_batch_response_by_index,
        text_fallback_backend=text_fallback_backend,
        failover_enabled=failover_enabled,
    )

    # Собираем TEXT/TABLE блоки
    for block_id, parts_dict in text_block_parts.items():
        if block_id not in blocks_by_id:
            continue
        block = blocks_by_id[block_id]
        total_parts = text_block_total_parts.get(block_id, 1)
        if total_parts == 1:
            block.ocr_text = parts_dict.get(0, "")
        else:
            combined = [parts_dict.get(i, "") for i in range(total_parts)]
            block.ocr_text = "\n\n".join(combined)
        logger.info(
            f"PASS2 ASYNC TEXT блок {block_id}: ocr_text длина = "
            f"{len(block.ocr_text) if block.ocr_text else 0}"
        )

    text_block_parts.clear()
    text_block_total_parts.clear()
    log_memory_delta("PASS2 ASYNC после strips", start_mem)

    # ═══ PHASE 2: IMAGES ═══
    checkpoint.phase = "pass2_images"
    logger.info(
        f"PASS2 ASYNC: обработка {len(manifest.image_blocks)} image blocks "
        f"({max_workers} workers, bounded queue)"
    )

    image_block_parts, image_block_total_parts = await run_image_phase(
        manifest.image_blocks,
        blocks_by_id=blocks_by_id,
        image_backend=image_backend,
        stamp_backend=stamp_backend,
        pdf_path=pdf_path,
        checkpoint=checkpoint,
        rate_limiter=rate_limiter,
        max_workers=max_workers,
        is_paused_fn=is_paused_fn,
        deadline=deadline,
        max_retries=image_max_retries,
        retry_delays=image_retry_delays,
        state=state,
        total_requests=total_requests,
        on_progress=on_progress,
        checkpoint_path=checkpoint_path,
        extract_pdfplumber_text_for_block=extract_pdfplumber_text_for_block,
        fill_image_prompt_variables=fill_image_prompt_variables,
        inject_pdfplumber_to_ocr_text=inject_pdfplumber_to_ocr_text,
    )

    # Собираем IMAGE блоки
    for block_id, parts_dict in image_block_parts.items():
        if block_id not in blocks_by_id:
            continue
        block = blocks_by_id[block_id]
        total_parts = image_block_total_parts.get(block_id, 1)
        if total_parts == 1:
            block.ocr_text = parts_dict.get(0, "")
        else:
            combined = [parts_dict.get(i, "") for i in range(total_parts)]
            block.ocr_text = "\n\n".join(combined)
        logger.info(
            f"PASS2 ASYNC IMAGE блок {block_id}: ocr_text длина = "
            f"{len(block.ocr_text) if block.ocr_text else 0}"
        )

    image_block_parts.clear()
    image_block_total_parts.clear()

    # Финальный checkpoint
    checkpoint.phase = "completed"
    if checkpoint_path:
        await asyncio.to_thread(checkpoint.save, checkpoint_path)
        logger.info(f"Финальный checkpoint сохранён: {checkpoint_path}")

    force_gc("PASS2 ASYNC завершён")
    log_memory_delta("PASS2 ASYNC end", start_mem)

    logger.info(f"PASS2 ASYNC завершён: {state.processed} запросов обработано")


def pass2_ocr_from_manifest_sync_wrapper(
    manifest: TwoPassManifest,
    blocks: List,
    strip_backend,
    image_backend,
    stamp_backend,
    pdf_path: str,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    check_paused: Optional[Callable[[], bool]] = None,
    checkpoint: Optional[OCRCheckpoint] = None,
    work_dir: Optional[Path] = None,
) -> None:
    """Синхронная обёртка для async pass2_ocr (для Celery task)."""
    asyncio.run(
        pass2_ocr_from_manifest_async(
            manifest=manifest,
            blocks=blocks,
            strip_backend=strip_backend,
            image_backend=image_backend,
            stamp_backend=stamp_backend,
            pdf_path=pdf_path,
            on_progress=on_progress,
            check_paused=check_paused,
            checkpoint=checkpoint,
            work_dir=work_dir,
        )
    )
