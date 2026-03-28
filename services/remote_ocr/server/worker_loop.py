"""Persistent asyncio event loop для Celery worker.

Вместо asyncio.run() (создаёт/уничтожает event loop на каждую задачу)
используем один persistent loop на весь lifetime worker process.
Это решает проблему привязки asyncio.Lock к конкретному loop.

Использование:
    from .worker_loop import run_async
    result = run_async(some_coroutine(args))
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Создать persistent event loop в отдельном daemon thread (lazy init)."""
    global _loop, _thread

    if _loop is not None and _loop.is_running():
        return _loop

    with _lock:
        # Double-check after lock
        if _loop is not None and _loop.is_running():
            return _loop

        _loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _thread = threading.Thread(target=_run_loop, daemon=True, name="worker-asyncio-loop")
        _thread.start()
        logger.info("Persistent asyncio event loop started (worker-level)")

    return _loop


def run_async(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """Выполнить coroutine в persistent event loop.

    Замена для asyncio.run() в Celery worker context.
    Thread-safe: может вызываться из любого worker thread.

    Args:
        coro: корутина для выполнения
        timeout: опциональный таймаут в секундах

    Returns:
        Результат корутины
    """
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def shutdown_loop() -> None:
    """Остановить persistent event loop (при завершении worker)."""
    global _loop, _thread

    if _loop is not None and _loop.is_running():
        _loop.call_soon_threadsafe(_loop.stop)
        if _thread is not None:
            _thread.join(timeout=5)
        logger.info("Persistent asyncio event loop stopped")

    _loop = None
    _thread = None
