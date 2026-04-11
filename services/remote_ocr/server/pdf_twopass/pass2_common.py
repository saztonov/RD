"""Общие утилиты для pass2 OCR: retry, checkpoint, pause, progress."""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Callable, Optional

from ..logging_config import get_logger
from ..ocr_constants import is_error, is_non_retriable

logger = get_logger(__name__)

# Интервал сохранения checkpoint (каждые N обработанных элементов)
CHECKPOINT_SAVE_INTERVAL = 10

# Sentinel для обнаружения отмены во время OCR-запроса
CANCELLED_SENTINEL = object()

# Резерв времени для upload/finalize (секунды)
DEADLINE_RESERVE = 120


def should_retry_ocr(text: Optional[str], item_id: str, attempt: int, max_retries: int) -> bool:
    """Проверить результат OCR и решить, нужен ли retry."""
    if text and not is_error(text):
        return False
    if is_non_retriable(text):
        logger.warning(f"PASS2 ASYNC: {item_id} неповторяемая ошибка, пропускаем retry")
        return False
    if attempt < max_retries:
        err_preview = (text or "пусто")[:80]
        logger.warning(f"PASS2 ASYNC: {item_id} ошибка OCR ({err_preview}), будет retry")
        return True
    return False


def get_retry_params(backend_name: str) -> tuple:
    """Получить параметры retry по типу бэкенда.

    Returns:
        (max_retries, retry_delays, is_lmstudio)
    """
    is_lmstudio = backend_name in ("ChandraBackend",)
    if is_lmstudio:
        # Chandra: 2 дополнительных попытки на уровне strip перед тем как отдать ошибку.
        # Нужно при флапсах ngrok / "Model unloaded" / транзиентных 5xx.
        # Backend делает свой внутренний retry (chandra_request_retries), strip-level
        # ещё 2 — этого достаточно, чтобы пережить короткие сетевые сбои.
        return 2, [5, 15], True
    return 1, [5], False


@dataclasses.dataclass
class Pass2RuntimeState:
    """Shared mutable state для pass2 orchestration."""

    processed: int = 0
    processed_lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    checkpoint_counter: int = 0
    last_block_info: str = ""


async def save_checkpoint_if_needed(
    state: Pass2RuntimeState,
    checkpoint,
    checkpoint_path: Optional[Path],
) -> None:
    """Сохранить checkpoint каждые N элементов."""
    state.checkpoint_counter += 1
    if checkpoint_path and state.checkpoint_counter % CHECKPOINT_SAVE_INTERVAL == 0:
        await asyncio.to_thread(checkpoint.save, checkpoint_path)


def make_pause_checker(check_paused: Optional[Callable[[], bool]]) -> Callable[[], bool]:
    """Обернуть check_paused в безопасную функцию."""
    if not check_paused:
        return lambda: False

    def _is_paused() -> bool:
        try:
            return check_paused()
        except Exception as exc:
            logger.warning(f"PASS2 ASYNC: ошибка в check_paused: {exc}")
            return False

    return _is_paused


async def cancellable_recognize(backend, *args, is_paused_fn, check_interval=5.0):
    """Вызов backend.recognize с проверкой отмены."""
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(None, backend.recognize, *args)
    while True:
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=check_interval)
        except asyncio.TimeoutError:
            if is_paused_fn():
                future.cancel()
                logger.info("PASS2 ASYNC: OCR-запрос прерван — задача отменена")
                return CANCELLED_SENTINEL


def drain_queue(queue: asyncio.Queue) -> None:
    """Очистить очередь при отмене."""
    while not queue.empty():
        try:
            queue.get_nowait()
            queue.task_done()
        except asyncio.QueueEmpty:
            break


async def update_progress(
    state: Pass2RuntimeState,
    total_requests: int,
    on_progress: Optional[Callable],
    block_info: str = None,
) -> None:
    """Обновить прогресс."""
    async with state.processed_lock:
        state.processed += 1
        if block_info:
            state.last_block_info = block_info
        if on_progress and total_requests > 0:
            try:
                await asyncio.to_thread(
                    on_progress, state.processed, total_requests, state.last_block_info
                )
            except Exception as exc:
                logger.warning(f"PASS2 ASYNC: ошибка в on_progress callback: {exc}")
