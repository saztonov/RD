from __future__ import annotations

from .storage import FileTaskStore, Task, TaskStatus


def process_task(store: FileTaskStore, task: Task) -> Task:
    # TODO: реальная обработка OCR будет добавлена на следующих этапах.
    task.status = TaskStatus.done
    task.result = {"ok": True}
    store.update(task)
    return task


