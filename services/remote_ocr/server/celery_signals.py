"""Celery signals для логирования lifecycle задач.

Автоматически логирует:
- Старт/остановка воркера
- Начало/завершение задач
- Ошибки и retry

Подключается автоматически при импорте в celery_app.py.
"""

from __future__ import annotations

import time
from typing import Any

from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_ready,
    worker_shutdown,
)

from .logging_config import get_logger
from .memory_utils import get_memory_mb

logger = get_logger(__name__)

# Хранение времени старта задач для вычисления duration
_task_start_times: dict[str, float] = {}


@worker_ready.connect
def on_worker_ready(sender: Any = None, **kwargs: Any) -> None:
    """Логирование при старте воркера."""
    from .settings import settings

    logger.info(
        "Celery worker started",
        extra={
            "event": "worker_ready",
            "concurrency": settings.max_concurrent_jobs,
            "prefetch": settings.worker_prefetch,
            "max_tasks_per_child": settings.worker_max_tasks,
        },
    )


@worker_shutdown.connect
def on_worker_shutdown(sender: Any = None, **kwargs: Any) -> None:
    """Логирование при остановке воркера."""
    logger.info("Celery worker shutdown", extra={"event": "worker_shutdown"})


@task_prerun.connect
def on_task_prerun(
    sender: Any = None,
    task_id: str | None = None,
    task: Any = None,
    args: tuple[Any, ...] | None = None,
    **kwargs: Any,
) -> None:
    """Логирование перед выполнением задачи."""
    job_id = args[0] if args else None
    if task_id:
        _task_start_times[task_id] = time.time()

    task_name = task.name if task else "unknown"

    logger.info(
        f"Task started: {task_name}",
        extra={
            "event": "task_prerun",
            "task_id": task_id,
            "task_name": task_name,
            "job_id": job_id,
            "memory_mb": get_memory_mb(),
        },
    )


@task_postrun.connect
def on_task_postrun(
    sender: Any = None,
    task_id: str | None = None,
    task: Any = None,
    args: tuple[Any, ...] | None = None,
    retval: Any = None,
    state: str | None = None,
    **kwargs: Any,
) -> None:
    """Логирование после выполнения задачи."""
    job_id = args[0] if args else None
    start_time = _task_start_times.pop(task_id, None) if task_id else None
    duration_ms = int((time.time() - start_time) * 1000) if start_time else None

    # Извлекаем статус из результата или используем state
    status = retval.get("status") if isinstance(retval, dict) else state
    task_name = task.name if task else "unknown"

    logger.info(
        f"Task completed: {task_name}",
        extra={
            "event": "task_postrun",
            "task_id": task_id,
            "task_name": task_name,
            "job_id": job_id,
            "status": status,
            "duration_ms": duration_ms,
            "memory_mb": get_memory_mb(),
        },
    )


@task_failure.connect
def on_task_failure(
    sender: Any = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    args: tuple[Any, ...] | None = None,
    traceback: Any = None,
    **kwargs: Any,
) -> None:
    """Логирование при ошибке задачи."""
    job_id = args[0] if args else None
    start_time = _task_start_times.pop(task_id, None) if task_id else None
    duration_ms = int((time.time() - start_time) * 1000) if start_time else None

    task_name = sender.name if sender else "unknown"

    logger.error(
        f"Task failed: {task_name}",
        extra={
            "event": "task_failure",
            "task_id": task_id,
            "task_name": task_name,
            "job_id": job_id,
            "exception_type": type(exception).__name__ if exception else None,
            "exception_message": str(exception) if exception else None,
            "duration_ms": duration_ms,
            "memory_mb": get_memory_mb(),
        },
        exc_info=(type(exception), exception, traceback) if exception else None,
    )


@task_retry.connect
def on_task_retry(
    sender: Any = None,
    request: Any = None,
    reason: Any = None,
    **kwargs: Any,
) -> None:
    """Логирование при retry задачи."""
    task_name = sender.name if sender else "unknown"
    task_id = request.id if request else None
    job_id = request.args[0] if request and request.args else None
    retry_count = request.retries if request else 0

    logger.warning(
        f"Task retry: {task_name}",
        extra={
            "event": "task_retry",
            "task_id": task_id,
            "task_name": task_name,
            "job_id": job_id,
            "retry_reason": str(reason) if reason else None,
            "retry_count": retry_count,
        },
    )
