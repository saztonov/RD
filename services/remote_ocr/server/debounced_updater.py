"""Debounced job status updater to reduce Supabase load"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class UpdateState:
    """Tracks last update state for debouncing"""

    last_update_time: float = 0.0
    last_progress: float = 0.0
    last_status: str = ""
    pending_update: Optional[Dict[str, Any]] = None


class DebouncedJobUpdater:
    """
    Debounces job status updates to reduce Supabase load.

    Rules:
    - Writes no more than once per `min_interval_seconds`
    - OR when progress changes by more than `min_progress_delta`
    - ALWAYS flushes immediately on status change (done/error/paused/cancelled)
    """

    TERMINAL_STATUSES = {"done", "error", "paused", "cancelled"}

    def __init__(
        self,
        job_id: str,
        min_interval_seconds: float = 3.0,
        min_progress_delta: float = 0.05,
    ):
        self.job_id = job_id
        self.min_interval = min_interval_seconds
        self.min_progress_delta = min_progress_delta
        self._state = UpdateState()
        self._lock = threading.Lock()
        self._db_call_count = 0
        self._skipped_count = 0

    def update(
        self,
        status: str,
        progress: Optional[float] = None,
        error_message: Optional[str] = None,
        r2_prefix: Optional[str] = None,
        status_message: Optional[str] = None,
    ) -> bool:
        """
        Update job status with debouncing.

        Returns True if update was written, False if debounced.
        """
        from .storage_jobs import update_job_status as raw_update

        now = time.time()

        with self._lock:
            if status in self.TERMINAL_STATUSES:
                self._do_update(
                    raw_update, status, progress, error_message, r2_prefix, status_message
                )
                return True

            time_elapsed = now - self._state.last_update_time
            progress_delta = abs((progress or 0) - self._state.last_progress)
            status_changed = status != self._state.last_status

            should_update = (
                status_changed
                or time_elapsed >= self.min_interval
                or progress_delta >= self.min_progress_delta
            )

            if should_update:
                self._do_update(
                    raw_update, status, progress, error_message, r2_prefix, status_message
                )
                return True
            else:
                self._state.pending_update = {
                    "status": status,
                    "progress": progress,
                    "error_message": error_message,
                    "r2_prefix": r2_prefix,
                    "status_message": status_message,
                }
                self._skipped_count += 1
                return False

    def _do_update(
        self,
        raw_update,
        status: str,
        progress: Optional[float],
        error_message: Optional[str],
        r2_prefix: Optional[str],
        status_message: Optional[str],
    ) -> None:
        """Execute the actual database update"""
        raw_update(
            self.job_id,
            status,
            progress=progress,
            error_message=error_message,
            r2_prefix=r2_prefix,
            status_message=status_message,
        )
        self._state.last_update_time = time.time()
        self._state.last_progress = progress or 0
        self._state.last_status = status
        self._state.pending_update = None
        self._db_call_count += 1

    def flush(self) -> bool:
        """Flush any pending update"""
        from .storage_jobs import update_job_status as raw_update

        with self._lock:
            if self._state.pending_update:
                upd = self._state.pending_update
                self._do_update(
                    raw_update,
                    upd["status"],
                    upd["progress"],
                    upd["error_message"],
                    upd["r2_prefix"],
                    upd["status_message"],
                )
                return True
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about updates"""
        total = self._db_call_count + self._skipped_count
        return {
            "db_calls": self._db_call_count,
            "skipped": self._skipped_count,
            "total_requests": total,
            "reduction_percent": round(100 * self._skipped_count / total, 1) if total > 0 else 0,
        }


_updaters: Dict[str, DebouncedJobUpdater] = {}
_updaters_lock = threading.Lock()


def get_debounced_updater(job_id: str) -> DebouncedJobUpdater:
    """Get or create debounced updater for a job"""
    with _updaters_lock:
        if job_id not in _updaters:
            _updaters[job_id] = DebouncedJobUpdater(job_id)
        return _updaters[job_id]


def cleanup_updater(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Cleanup updater for a job. Returns stats before cleanup.
    Should be called at job completion.
    """
    with _updaters_lock:
        if job_id in _updaters:
            updater = _updaters.pop(job_id)
            updater.flush()
            return updater.get_stats()
    return None
