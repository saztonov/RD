"""Thread-safe кеш OCR задач с оптимистичными обновлениями.

Извлечён из JobsController — единственный владелец _jobs_cache dict.
Все операции чтения/записи защищены threading.Lock.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Iterable, Optional

from rd_core.dto.jobs import JobInfoDTO

logger = logging.getLogger(__name__)

# Backward-compatible alias
JobInfo = JobInfoDTO


class JobsCache:
    """Thread-safe кеш задач + оптимистичные обновления + downloaded tracking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobInfo] = {}
        self._optimistic: dict[str, tuple[JobInfo, float]] = {}
        self._downloaded: set[str] = set()
        self._downloading: set[str] = set()
        self._orphan: set[str] = set()  # задачи, исчезнувшие с сервера (404)
        self._cleared: set[str] = set()  # id, явно очищенные пользователем
        self._last_server_time: Optional[str] = None

    # ── Read operations ──────────────────────────────────────────────

    def get(self, job_id: str) -> Optional[JobInfo]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_all(self) -> list[JobInfo]:
        with self._lock:
            return list(self._jobs.values())

    def get_all_sorted(self) -> list[JobInfo]:
        jobs = self.get_all()
        jobs.sort(key=lambda j: (j.priority, j.created_at))
        return jobs

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)

    def __bool__(self) -> bool:
        with self._lock:
            return bool(self._jobs)

    @property
    def last_server_time(self) -> Optional[str]:
        return self._last_server_time

    @last_server_time.setter
    def last_server_time(self, value: Optional[str]) -> None:
        self._last_server_time = value

    # ── Write operations ─────────────────────────────────────────────

    def update_delta(self, jobs: list[JobInfo], server_time: Optional[str] = None) -> list[JobInfo]:
        """Обновить кеш дельтой и вернуть полный список.

        Задачи из `_cleared` или `_orphan` игнорируются — пользователь явно
        удалил их или сервер ответил 404, возвращать их в UI нельзя.
        """
        with self._lock:
            for job in jobs:
                if job.id in self._cleared or job.id in self._orphan:
                    continue
                self._jobs[job.id] = job
            if server_time:
                self._last_server_time = server_time
            return list(self._jobs.values())

    def replace_all(self, jobs: list[JobInfo], server_time: Optional[str] = None) -> None:
        """Полная замена кеша (первая загрузка или manual refresh).

        cleared/orphan id отфильтровываются — иначе после очистки
        список бы воскресал на ближайшем full-refresh.
        """
        with self._lock:
            self._jobs = {
                j.id: j
                for j in jobs
                if j.id not in self._cleared and j.id not in self._orphan
            }
            if server_time:
                self._last_server_time = server_time

    def set_status(self, job_id: str, status: str) -> Optional[JobInfo]:
        """Оптимистичное обновление статуса. Возвращает job или None."""
        with self._lock:
            cached = self._jobs.get(job_id)
            if cached:
                cached.status = status
            return cached

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    def clear(self) -> list[str]:
        """Очистить кеш, вернуть ID всех задач.

        Возвращённые id маркируются как cleared, чтобы delta/full refresh,
        восстановление из snapshot и merge_optimistic не возвращали их в UI
        даже если серверный DELETE упал или гонкой пришёл «свежий» ответ
        со старыми задачами.
        """
        with self._lock:
            job_ids = [j.id for j in self._jobs.values()]
            self._jobs.clear()
            self._cleared.update(job_ids)
            for jid in job_ids:
                self._optimistic.pop(jid, None)
            self._downloaded.difference_update(job_ids)
            self._downloading.difference_update(job_ids)
            return job_ids

    def log_status_changes(self, incoming_jobs: list[JobInfo]) -> None:
        """Залогировать изменения статусов."""
        with self._lock:
            for job in incoming_jobs:
                cached = self._jobs.get(job.id)
                if cached and cached.status != job.status:
                    logger.info(
                        f"Статус задачи {job.id[:8]}... изменился: "
                        f"{cached.status} -> {job.status} (progress={job.progress:.0%})"
                    )

    # ── Optimistic jobs ──────────────────────────────────────────────

    def add_optimistic(self, job_id: str, job: JobInfo) -> None:
        self._optimistic[job_id] = (job, time.time())

    def remove_optimistic(self, job_id: str) -> None:
        self._optimistic.pop(job_id, None)

    def remove_uploading_optimistic(self) -> None:
        """Удалить все оптимистичные задачи со статусом uploading."""
        uploading_ids = [
            jid for jid, (job, _) in self._optimistic.items()
            if job.status == "uploading"
        ]
        for jid in uploading_ids:
            self._optimistic.pop(jid, None)

    def merge_optimistic(self, server_jobs: list[JobInfo]) -> list[JobInfo]:
        """Объединить серверные задачи с оптимистичными. Возвращает merged list.

        Любые id из `_cleared`/`_orphan` отфильтровываются на обеих сторонах.
        """
        merged = [
            j for j in server_jobs
            if j.id not in self._cleared and j.id not in self._orphan
        ]
        server_ids = {j.id for j in merged}
        current_time = time.time()

        for job_id, (job_info, timestamp) in list(self._optimistic.items()):
            if job_id in self._cleared or job_id in self._orphan:
                self._optimistic.pop(job_id, None)
                continue
            if job_id in server_ids:
                logger.info(
                    f"Задача {job_id[:8]}... найдена в ответе сервера, "
                    "удаляем из оптимистичного списка"
                )
                self._optimistic.pop(job_id, None)
            elif current_time - timestamp > 60:
                logger.warning(
                    f"Задача {job_id[:8]}... в оптимистичном списке более минуты, "
                    "удаляем (таймаут)"
                )
                self._optimistic.pop(job_id, None)
            else:
                merged.insert(0, job_info)

        return merged

    # ── Download tracking ────────────────────────────────────────────

    def is_downloaded(self, job_id: str) -> bool:
        return job_id in self._downloaded

    def mark_downloaded(self, job_id: str) -> None:
        self._downloaded.add(job_id)

    def is_downloading(self, job_id: str) -> bool:
        return job_id in self._downloading

    def mark_downloading(self, job_id: str) -> None:
        self._downloading.add(job_id)

    def unmark_downloading(self, job_id: str) -> None:
        self._downloading.discard(job_id)

    def mark_node_downloads_complete(self, node_id: str) -> None:
        """Пометить done/partial-джобы для node как скачанные."""
        with self._lock:
            for job_id, job in self._jobs.items():
                if job.status in ("done", "partial") and getattr(job, "node_id", None) == node_id:
                    self._downloaded.add(job_id)

    def reset_node_downloads(self, node_id: str) -> None:
        """Сбросить downloaded-метки для node."""
        with self._lock:
            to_remove = set()
            for jid in self._downloaded:
                cached = self._jobs.get(jid)
                if cached and getattr(cached, "node_id", None) == node_id:
                    to_remove.add(jid)
            self._downloaded -= to_remove

    def get_active_for_node(self, node_id: str) -> list[JobInfo]:
        """Получить активные задачи для конкретного node."""
        with self._lock:
            return [
                j for j in self._jobs.values()
                if j.status in ("queued", "processing", "paused")
                and getattr(j, "node_id", None) == node_id
            ]

    # ── Orphan tracking (server 404) ─────────────────────────────────

    def is_orphan(self, job_id: str) -> bool:
        return job_id in self._orphan

    def mark_orphan(self, job_id: str) -> None:
        """Пометить задачу как удалённую с сервера (404).

        Удаляет из основного кеша и трекинга скачивания —
        auto-download больше не будет её брать.
        """
        with self._lock:
            self._orphan.add(job_id)
            self._jobs.pop(job_id, None)
        self._downloaded.discard(job_id)
        self._downloading.discard(job_id)
        logger.info(f"Задача {job_id[:8]}... помечена как orphan (404)")

    def clear_orphans(self) -> None:
        self._orphan.clear()

    def get_orphans(self) -> set[str]:
        """Вернуть копию orphan-set для сериализации в snapshot."""
        with self._lock:
            return set(self._orphan)

    def load_orphans(self, orphan_ids) -> None:
        """Восстановить orphan-set из snapshot. Должно вызываться ДО replace_all,
        чтобы фильтрация работала корректно."""
        with self._lock:
            self._orphan.update(orphan_ids)

    # ── Cleared tracking (user-initiated clear-all) ──────────────────

    def is_cleared(self, job_id: str) -> bool:
        return job_id in self._cleared

    def mark_cleared(self, job_ids: Iterable[str]) -> None:
        """Пометить задачи как очищенные пользователем.

        Удаляет их из активного кеша, оптимистичных и downloaded/downloading
        наборов. Cleared id переживает рестарт (через snapshot) и фильтруется
        во всех write-операциях кеша.
        """
        ids = list(job_ids)
        if not ids:
            return
        with self._lock:
            self._cleared.update(ids)
            for jid in ids:
                self._jobs.pop(jid, None)
                self._optimistic.pop(jid, None)
            self._downloaded.difference_update(ids)
            self._downloading.difference_update(ids)

    def get_cleared_ids(self) -> set[str]:
        """Копия cleared-set для сериализации в snapshot."""
        with self._lock:
            return set(self._cleared)

    def load_cleared_ids(self, ids) -> None:
        """Восстановить cleared-set из snapshot. Должно вызываться ДО replace_all,
        чтобы фильтрация работала корректно."""
        with self._lock:
            self._cleared.update(ids)

    def prune_cleared(self, present_server_ids: set[str]) -> None:
        """Удалить из cleared id, которых уже нет в серверном списке.

        Вызывать после успешного full-refresh: если id отсутствует в свежем
        ответе сервера, значит DELETE прошёл и удерживать его в cleared
        больше не нужно — set не разрастается.
        """
        with self._lock:
            stale = self._cleared - present_server_ids
            if stale:
                self._cleared.difference_update(stale)
                logger.debug(
                    f"prune_cleared: удалено {len(stale)} подтверждённых id "
                    f"(осталось {len(self._cleared)})"
                )
