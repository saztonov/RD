"""Polling controller для OCR задач.

Управляет таймером опроса с адаптивными интервалами:
- Панель видима + активные задачи: 5s
- Панель видима + idle: 30s
- Панель скрыта + активные: 15s
- Панель скрыта + idle: таймер остановлен
- Ошибки: exponential backoff до 5 минут
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject, QTimer, Signal

if TYPE_CHECKING:
    from app.gui.remote_ocr.jobs_cache import JobsCache

logger = logging.getLogger(__name__)

# Polling intervals (ms)
POLL_VISIBLE_ACTIVE = 5000
POLL_VISIBLE_IDLE = 30000
POLL_HIDDEN_ACTIVE = 15000
POLL_ERROR_BASE = 120000
POLL_ERROR_MAX = 300000


class PollingController(QObject):
    """Управляет polling-таймером и fetch-логикой."""

    # Signals для координатора
    fetch_requested = Signal(bool)  # force_full

    def __init__(self, cache: JobsCache, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._panel_visible = False
        self._has_active_jobs = False
        self._is_fetching = False
        self._is_manual_refresh = False
        self._force_full_refresh = False
        self._consecutive_errors = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

    # ── Public API ───────────────────────────────────────────────────

    def set_panel_visible(self, visible: bool) -> None:
        self._panel_visible = visible
        self._adjust_interval()

    def request_refresh(self, *, force_full: bool = False, show_loading: bool = False) -> bool:
        """Запросить refresh. Возвращает True если запрос принят."""
        if self._is_fetching:
            return False

        if not force_full and not show_loading:
            if self._consecutive_errors >= 3:
                return False

        self._is_fetching = True
        self._is_manual_refresh = force_full
        if force_full:
            self._force_full_refresh = True
        return True

    def on_fetch_success(self, has_active_jobs: bool) -> None:
        """Вызывается после успешного fetch."""
        self._is_fetching = False
        self._is_manual_refresh = False
        self._force_full_refresh = False
        self._consecutive_errors = 0
        self._has_active_jobs = has_active_jobs
        self._adjust_interval()

    def on_fetch_error(self, was_delta: bool) -> None:
        """Вызывается при ошибке fetch."""
        self._is_fetching = False
        self._consecutive_errors += 1
        if was_delta:
            self._force_full_refresh = True

        backoff = min(
            POLL_ERROR_BASE * (2 ** min(self._consecutive_errors - 1, 3)),
            POLL_ERROR_MAX,
        )
        if self._timer.interval() != backoff:
            self._timer.setInterval(backoff)
        if not self._timer.isActive():
            self._timer.start()

    def on_health_check_success(self) -> None:
        """Сбросить backoff после успешного health check."""
        self._consecutive_errors = 0
        self._force_full_refresh = True
        self._adjust_interval()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def should_use_delta(self) -> bool:
        """Нужно ли делать delta-запрос (vs full)."""
        return bool(
            self._cache.last_server_time
            and self._cache
            and not self._force_full_refresh
        )

    @property
    def is_manual_refresh(self) -> bool:
        return self._is_manual_refresh

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    # ── Private ──────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        self.fetch_requested.emit(False)

    def _adjust_interval(self) -> None:
        if self._panel_visible:
            interval = POLL_VISIBLE_ACTIVE if self._has_active_jobs else POLL_VISIBLE_IDLE
        else:
            if self._has_active_jobs:
                interval = POLL_HIDDEN_ACTIVE
            else:
                self._timer.stop()
                return

        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        if not self._timer.isActive():
            self._timer.start()
