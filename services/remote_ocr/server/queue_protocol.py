"""Queue dispatcher protocol — абстракция для замены Celery.

Определяет интерфейс для dispatch/cancel/inspect задач.
Текущая реализация: CeleryDispatcher (в tasks.py/task_dispatch.py).
Будущая: ArqDispatcher или asyncio-native.

Использование:
    dispatcher: QueueDispatcher = get_dispatcher()
    task_id = dispatcher.dispatch("job-123", priority=5)
    dispatcher.cancel(task_id)
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class QueueDispatcher(Protocol):
    """Protocol для диспетчера очереди задач."""

    def dispatch(
        self,
        job_id: str,
        priority: int = 0,
        countdown: float = 0,
    ) -> str:
        """Отправить задачу в очередь.

        Args:
            job_id: ID задачи.
            priority: Приоритет (0=normal, 10=high).
            countdown: Задержка перед выполнением (секунды).

        Returns:
            celery_task_id или аналог.
        """
        ...

    def cancel(self, task_id: str) -> bool:
        """Отменить задачу по task_id.

        Returns:
            True если отмена отправлена.
        """
        ...

    def is_active(self, task_id: str) -> Optional[bool]:
        """Проверить активна ли задача.

        Returns:
            True если активна, False если нет, None если не удалось определить.
        """
        ...

    def get_active_task_ids(self) -> Optional[set[str]]:
        """Получить set активных task_id.

        Returns:
            Set of task IDs, or None if inspection failed.
        """
        ...


class CeleryDispatcher:
    """Реализация QueueDispatcher через Celery."""

    def dispatch(
        self,
        job_id: str,
        priority: int = 0,
        countdown: float = 0,
    ) -> str:
        from .tasks import process_ocr_job

        result = process_ocr_job.apply_async(
            args=[job_id],
            priority=priority,
            countdown=countdown,
        )
        return result.id

    def cancel(self, task_id: str) -> bool:
        from .celery_app import celery_app

        try:
            celery_app.control.revoke(task_id, terminate=True, signal="SIGUSR1")
            return True
        except Exception:
            return False

    def is_active(self, task_id: str) -> Optional[bool]:
        active_ids = self.get_active_task_ids()
        if active_ids is None:
            return None
        return task_id in active_ids

    def get_active_task_ids(self) -> Optional[set[str]]:
        from .celery_app import celery_app

        try:
            inspect = celery_app.control.inspect()
            active = inspect.active()
            if active is None:
                return None
            ids = set()
            for worker_tasks in active.values():
                for task in worker_tasks:
                    ids.add(task["id"])
            return ids
        except Exception:
            return None


_dispatcher: Optional[QueueDispatcher] = None


def get_dispatcher() -> QueueDispatcher:
    """Получить текущий dispatcher (по умолчанию Celery)."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = CeleryDispatcher()
    return _dispatcher


def set_dispatcher(dispatcher: QueueDispatcher) -> None:
    """Заменить dispatcher (для тестов или миграции на arq)."""
    global _dispatcher
    _dispatcher = dispatcher
