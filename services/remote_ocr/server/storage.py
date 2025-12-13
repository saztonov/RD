from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


@dataclass
class Task:
    id: str
    status: TaskStatus = TaskStatus.queued
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


def task_to_dict(task: Task) -> dict[str, Any]:
    d = asdict(task)
    d["status"] = task.status.value
    return d


class FileTaskStore:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def create(self, payload: dict[str, Any]) -> Task:
        task = Task(id=str(uuid.uuid4()), payload=payload)
        with self._lock:
            data = self._read_all()
            data[task.id] = task_to_dict(task)
            self._write_all(data)
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            data = self._read_all()
            raw = data.get(task_id)
            if raw is None:
                return None
            return self._deserialize(raw)

    def update(self, task: Task) -> None:
        with self._lock:
            data = self._read_all()
            data[task.id] = task_to_dict(task)
            self._write_all(data)

    def _read_all(self) -> dict[str, Any]:
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_all(self, data: dict[str, Any]) -> None:
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    @staticmethod
    def _deserialize(d: dict[str, Any]) -> Task:
        return Task(
            id=d["id"],
            status=TaskStatus(d["status"]),
            payload=d.get("payload"),
            result=d.get("result"),
            error=d.get("error"),
        )


