"""Контроллер бизнес-логики Remote OCR задач.

Тонкий QObject-фасад: сигналы, __init__, wiring и lifecycle-операции.
Создание задач, refresh/polling и download/results вынесены в миксины.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject, Signal

from app.gui.remote_ocr.download_mixin import DownloadOrchestrator
from app.gui.remote_ocr.job_persistence import load_snapshot
from app.gui.remote_ocr.jobs_cache import JobsCache
from app.gui.remote_ocr.jobs_controller_create_mixin import JobsControllerCreateMixin
from app.gui.remote_ocr.jobs_controller_refresh_mixin import JobsControllerRefreshMixin
from app.gui.remote_ocr.jobs_controller_results_mixin import JobsControllerResultsMixin
from app.gui.remote_ocr.polling_controller import PollingController

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow
    from app.ocr_client import RemoteOCRClient

from rd_core.dto.jobs import JobInfoDTO as JobInfo

logger = logging.getLogger(__name__)


class JobsController(
    JobsControllerCreateMixin,
    JobsControllerRefreshMixin,
    JobsControllerResultsMixin,
    QObject,
):
    """Контроллер состояния и бизнес-логики Remote OCR задач.

    Владеет:
      - кешем задач, оптимистичными задачами, множеством скачанных
      - polling-таймером с адаптивными интервалами
      - ThreadPoolExecutor для фоновых операций
    """

    # ── Сигналы (для UI) ──────────────────────────────────────────────

    jobs_updated = Signal(list)
    connection_status = Signal(str)
    job_uploading = Signal(object)
    job_created = Signal(object)
    job_create_error = Signal(str, str)
    download_started = Signal(str, int)
    download_progress = Signal(str, int, str)
    download_finished = Signal(str, str)
    download_error = Signal(str, str)

    # ── Внутренний объект сигналов для thread-safe emit ────────────────

    class _WorkerSignals(QObject):
        """Промежуточные сигналы из ThreadPoolExecutor."""

        jobs_loaded = Signal(list, str)
        jobs_error = Signal(str)
        job_created = Signal(object)
        job_create_error = Signal(str, str)
        lifecycle_result = Signal(str, bool, str)
        download_started = Signal(str, int)
        download_progress = Signal(str, int, str)
        download_finished = Signal(str, str)
        download_error = Signal(str, str)
        job_details_loaded = Signal(dict)

    # ── __init__ ──────────────────────────────────────────────────────

    def __init__(self, main_window: MainWindow, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.main_window = main_window

        # ── Компоненты ───────────────────────────────────────────────
        self._cache = JobsCache()
        self._poller = PollingController(self._cache, self)
        self._downloader = DownloadOrchestrator(self._cache, self)

        # Client
        self._client: Optional[RemoteOCRClient] = None

        # Контекст последнего создания
        self._last_output_dir: Optional[str] = None
        self._last_engine: Optional[str] = None
        self._pending_output_dir: Optional[str] = None
        self._is_correction_mode: bool = False

        # Executor + worker signals
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._worker = self._WorkerSignals()
        self._connect_worker_signals()

        # Polling — делегируем PollingController
        self._poller.fetch_requested.connect(lambda force: self.refresh(force_full=force))

        # Download signals — пробрасываем наружу
        self._downloader.download_started.connect(self.download_started)
        self._downloader.download_progress.connect(self.download_progress)
        self._downloader.download_finished.connect(self._on_download_finished)
        self._downloader.download_error.connect(self._on_download_error)

        # Загружаем snapshot для мгновенного показа
        load_snapshot(self._cache)

    # ── Подключение worker-сигналов ───────────────────────────────────

    def _connect_worker_signals(self) -> None:
        self._worker.jobs_loaded.connect(self._on_jobs_loaded)
        self._worker.jobs_error.connect(self._on_jobs_error)
        self._worker.job_created.connect(self._on_job_created)
        self._worker.job_create_error.connect(self._on_job_create_error)
        self._worker.download_started.connect(self._on_download_started)
        self._worker.download_progress.connect(self._on_download_progress)
        self._worker.download_finished.connect(self._on_download_finished)
        self._worker.download_error.connect(self._on_download_error)
        self._worker.lifecycle_result.connect(self._on_lifecycle_result)
        self._worker.job_details_loaded.connect(self._on_job_details_loaded)

    # ══════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════════════

    def set_panel_visible(self, visible: bool) -> None:
        """Уведомить контроллер о видимости панели — управляет polling."""
        self._poller.set_panel_visible(visible)
        if visible:
            has_snapshot = bool(self._cache)
            logger.info(
                f"Panel visible: has_snapshot={has_snapshot}, "
                f"cache_size={len(self._cache)}, "
                f"server_time={self._cache.last_server_time}"
            )
            self.refresh(force_full=not has_snapshot, show_loading=not has_snapshot)

    # create_job — в JobsControllerCreateMixin
    # refresh — в JobsControllerRefreshMixin

    def cancel_job(self, job_id: str) -> None:
        """Отменить задачу (в background)."""
        client = self._get_client()
        if client is None:
            return
        self._cache.set_status(job_id, "cancelled")
        self._emit_jobs_list()
        self._executor.submit(self._lifecycle_op_bg, "cancel", client.cancel_job, job_id)

    def resume_job(self, job_id: str) -> None:
        """Возобновить задачу с паузы (в background)."""
        client = self._get_client()
        if client is None:
            return
        self._cache.set_status(job_id, "queued")
        self._emit_jobs_list()
        self._executor.submit(self._lifecycle_op_bg, "resume", client.resume_job, job_id)

    def delete_job(self, job_id: str) -> None:
        """Удалить задачу (в background)."""
        client = self._get_client()
        if client is None:
            return
        self._cache.remove(job_id)
        self._emit_jobs_list()
        self._executor.submit(self._lifecycle_op_bg, "delete", client.delete_job, job_id)

    def cancel_all_jobs(self) -> None:
        """Отменить все активные задачи (queued/processing/paused)."""
        from PySide6.QtWidgets import QMessageBox

        client = self._get_client()
        if client is None:
            return

        cached_jobs = self._cache.get_all()
        active_jobs = [
            j for j in cached_jobs if j.status in ("queued", "processing", "paused")
        ]

        if not active_jobs:
            from app.gui.toast import show_toast
            show_toast(self.main_window, "Нет активных задач для отмены")
            return

        reply = QMessageBox.question(
            self.main_window,
            "Отмена задач",
            f"Отменить все активные задачи ({len(active_jobs)} шт.)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for job in active_jobs:
            self._cache.set_status(job.id, "cancelled")
        self._emit_jobs_list()

        job_ids = [j.id for j in active_jobs]
        self._executor.submit(self._cancel_all_bg, client, job_ids)

    def clear_all_jobs(self) -> None:
        """Очистить все задачи."""
        from PySide6.QtWidgets import QMessageBox

        client = self._get_client()
        if client is None:
            QMessageBox.warning(self.main_window, "Ошибка", "Клиент не инициализирован")
            return

        reply = QMessageBox.question(
            self.main_window,
            "Очистка задач",
            "Удалить все задачи из списка?\n\n"
            "- Файлы документов из дерева проектов сохранятся\n"
            "- Legacy файлы (без привязки к дереву) будут удалены",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        job_ids = self._cache.clear()
        self._emit_jobs_list()

        self._executor.submit(self._clear_all_bg, client, job_ids)

    def reorder_job(self, job_id: str, direction: str) -> None:
        """Переместить задачу вверх/вниз в очереди."""
        cached_job = self._cache.get(job_id)
        if not cached_job or cached_job.status != "queued":
            return

        client = self._get_client()
        if client is None:
            return

        label = "вверх" if direction == "up" else "вниз"
        self._executor.submit(
            self._lifecycle_op_bg, f"reorder_{label}",
            client.reorder_job, job_id, direction,
        )

    # ── Background lifecycle helpers ───────────────────────────────────

    def _lifecycle_op_bg(self, op_name: str, fn, *args) -> None:
        """Выполнить lifecycle-операцию в background."""
        try:
            ok = fn(*args)
            self._worker.lifecycle_result.emit(
                op_name, bool(ok),
                "" if ok else f"Операция {op_name} не выполнена",
            )
        except Exception as e:
            logger.error(f"Ошибка lifecycle-операции {op_name}: {e}")
            self._worker.lifecycle_result.emit(op_name, False, str(e))

    def _cancel_all_bg(self, client, job_ids: list[str]) -> None:
        cancelled = 0
        errors = 0
        for jid in job_ids:
            try:
                if client.cancel_job(jid):
                    cancelled += 1
                else:
                    errors += 1
            except Exception as e:
                logger.warning(f"Ошибка отмены задачи {jid}: {e}")
                errors += 1
        msg = f"Отменено {cancelled}" + (f", ошибок: {errors}" if errors else "")
        self._worker.lifecycle_result.emit("cancel_all", errors == 0, msg)

    def _clear_all_bg(self, client, job_ids: list[str]) -> None:
        deleted = 0
        errors = 0
        for jid in job_ids:
            try:
                if client.delete_job(jid):
                    deleted += 1
                else:
                    errors += 1
            except Exception as e:
                logger.warning(f"Ошибка удаления задачи {jid}: {e}")
                errors += 1
        msg = f"Удалено {deleted}" + (f", ошибок: {errors}" if errors else "")
        self._worker.lifecycle_result.emit("clear_all", errors == 0, msg)

    def _emit_jobs_list(self) -> None:
        """Эмитить текущий кэш задач."""
        all_jobs = self._cache.get_all_sorted()
        self.jobs_updated.emit(all_jobs)

    def _on_lifecycle_result(self, op_name: str, success: bool, message: str) -> None:
        from app.gui.toast import show_toast
        if message:
            show_toast(self.main_window, message)
        self.refresh(force_full=True)

    # ── show_job_details, auto_download_result, mark_node_downloads_complete
    # вынесены в миксины

    def update_ocr_stats(self) -> None:
        """Пересчитать и обновить статистику OCR."""
        mw = self.main_window
        if not mw.annotation_document:
            return
        panel = getattr(mw, "remote_ocr_panel", None)
        if panel and hasattr(panel, "update_ocr_stats"):
            panel.update_ocr_stats()

    def get_cached_job(self, job_id: str) -> Optional[JobInfo]:
        """Получить задачу из кеша по ID."""
        return self._cache.get(job_id)

    def shutdown(self) -> None:
        """Освободить ресурсы."""
        self._poller.stop()
        self._executor.shutdown(wait=False)

    # ── Snapshot ──────────────────────────────────────────────────────

    def has_snapshot(self) -> bool:
        return bool(self._cache)

    def get_snapshot_jobs(self) -> list:
        return self._cache.get_all_sorted()

    # ── Client ────────────────────────────────────────────────────────

    def _get_client(self) -> RemoteOCRClient | None:
        """Получить или создать клиент."""
        if self._client is None:
            try:
                import os

                from app.ocr_client import RemoteOCRClient

                base_url = os.getenv("REMOTE_OCR_BASE_URL", "http://localhost:8000")
                api_key = os.getenv("REMOTE_OCR_API_KEY")
                logger.info(
                    f"Creating RemoteOCRClient: REMOTE_OCR_BASE_URL={base_url}, "
                    f"API_KEY={'set' if api_key else 'NOT SET'}"
                )
                self._client = RemoteOCRClient()
                logger.info(f"Client created: base_url={self._client.base_url}")
            except Exception as e:
                logger.error(f"Ошибка создания клиента: {e}", exc_info=True)
                return None
        return self._client
