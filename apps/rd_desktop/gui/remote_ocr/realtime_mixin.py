"""Mixin for Supabase Realtime integration in Remote OCR panel."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Slot

if TYPE_CHECKING:
    from apps.rd_desktop.supabase_realtime import RealtimeJobMonitor

logger = logging.getLogger(__name__)


class RealtimeMixin:
    """
    Mixin for integrating Supabase Realtime into RemoteOCRPanel.

    Provides real-time job updates via WebSocket, with automatic
    fallback to HTTP polling when Realtime is unavailable.

    Features:
    - Instant job status updates via WebSocket
    - Reduced polling when Realtime is connected
    - Automatic reconnection with exponential backoff
    - Graceful fallback to polling on connection issues
    """

    # Polling interval when Realtime is connected (just for sync, much slower)
    POLL_INTERVAL_REALTIME = 120000  # 2 minutes

    def _init_realtime(self):
        """Initialize Realtime client (call from __init__)."""
        self._realtime_monitor = None
        self._realtime_enabled = self._should_use_realtime()

        if self._realtime_enabled:
            try:
                from apps.rd_desktop.supabase_realtime import RealtimeJobMonitor

                self._realtime_monitor = RealtimeJobMonitor(self)
                self._realtime_monitor.job_changed.connect(self._on_realtime_job_update)
                self._realtime_monitor.connection_status.connect(self._on_realtime_status)
                logger.info("Realtime monitor initialized")
            except ImportError as e:
                logger.warning(f"Realtime not available: {e}")
                self._realtime_enabled = False

    def _should_use_realtime(self) -> bool:
        """Check if Realtime should be used."""
        # Check for Supabase credentials
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_KEY", "")

        if not supabase_url or not supabase_key:
            logger.info("Supabase credentials not set, Realtime disabled")
            return False

        # Check environment variable to disable Realtime
        if os.getenv("DISABLE_REALTIME", "").lower() in ("1", "true", "yes"):
            logger.info("Realtime disabled via DISABLE_REALTIME env var")
            return False

        return True

    def _start_realtime(self):
        """Start Realtime connection (call after panel is shown)."""
        if self._realtime_monitor and self._realtime_enabled:
            logger.info("Starting Realtime connection...")
            self._realtime_monitor.start()

    def _stop_realtime(self):
        """Stop Realtime connection (call when panel is hidden)."""
        if self._realtime_monitor:
            self._realtime_monitor.stop()

    @Slot(object)
    def _on_realtime_job_update(self, job_info):
        """Handle real-time job update from WebSocket."""
        logger.debug(f"Realtime job update: {job_info.id[:8]}... status={job_info.status}")

        # Update cache
        self._jobs_cache[job_info.id] = job_info

        # Update table immediately
        self._update_single_job_in_table(job_info)

        # Check if this job is done and we should auto-download
        if job_info.status == "done" and job_info.id not in self._downloaded_jobs:
            if hasattr(self, "_auto_download_completed_jobs") and self._auto_download_completed_jobs:
                self._download_result(job_info.id)

    @Slot(str)
    def _on_realtime_status(self, status: str):
        """Handle Realtime connection status change."""
        if status == "realtime":
            # Connected to Realtime - slow down polling
            logger.info("Realtime connected, slowing down polling")
            self.status_label.setText("🟢 Realtime")
            if hasattr(self, "refresh_timer"):
                self.refresh_timer.setInterval(self.POLL_INTERVAL_REALTIME)
        elif status == "polling":
            # Disconnected - resume normal polling
            logger.info("Realtime disconnected, resuming normal polling")
            self.status_label.setText("🟡 Polling")
            if hasattr(self, "refresh_timer"):
                interval = (
                    self.POLL_INTERVAL_PROCESSING
                    if getattr(self, "_has_active_jobs", False)
                    else self.POLL_INTERVAL_IDLE
                )
                self.refresh_timer.setInterval(interval)
        else:
            self.status_label.setText("🔴 Отключено")

    def _update_single_job_in_table(self, job_info):
        """Update a single job row in the table without full refresh."""
        # Find existing row
        for row in range(self.jobs_table.rowCount()):
            row_job_id = self.jobs_table.item(row, 0)
            if row_job_id and row_job_id.data(0x100) == job_info.id:
                # Update existing row
                self._update_job_row(row, job_info)
                return

        # Job not found - add new row at top
        self._add_job_to_table(job_info, at_top=True)

    def _sync_realtime_cache(self, jobs):
        """Sync Realtime cache with polled jobs (for consistency)."""
        if self._realtime_monitor:
            self._realtime_monitor.update_job_cache(jobs)

    @property
    def is_realtime_connected(self) -> bool:
        """Check if Realtime is currently connected."""
        if self._realtime_monitor:
            return self._realtime_monitor.is_realtime_connected
        return False
