"""Миксин refresh/polling и auto-download логики для JobsController."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ocr_client import RemoteOCRClient

from app.gui.remote_ocr.job_persistence import save_snapshot

logger = logging.getLogger(__name__)


class JobsControllerRefreshMixin:
    """Refresh, polling, job details, auto-download candidate selection."""

    def refresh(self, *, force_full: bool = False, show_loading: bool = False) -> None:
        """Обновить список задач."""
        if not self._poller.request_refresh(force_full=force_full, show_loading=show_loading):
            return

        if self._poller.consecutive_errors >= 3:
            client = self._get_client()
            if client and client.health():
                self._poller.on_health_check_success()
            else:
                return

        if show_loading:
            self.connection_status.emit("loading")

        logger.info(f"Refresh: force_full={force_full}, show_loading={show_loading}")
        self._executor.submit(self._fetch_bg)

    # ── Background fetch ──────────────────────────────────────────────

    def _fetch_bg(self) -> None:
        """Фоновая загрузка задач (полная или дельта)."""
        client = self._get_client()
        if client is None:
            self._worker.jobs_error.emit("Ошибка клиента")
            return

        use_delta = self._poller.should_use_delta
        mode = "delta" if use_delta else "full"
        logger.info(f"Fetch started: mode={mode}, base_url={client.base_url}")
        t0 = time.time()

        try:
            if use_delta:
                jobs, server_time = client.list_jobs(since=self._cache.last_server_time)
                elapsed = time.time() - t0
                logger.info(
                    f"Fetch completed: mode=delta, changes={len(jobs)}, "
                    f"elapsed={elapsed:.2f}s"
                )
                all_jobs = self._cache.update_delta(jobs, server_time)
                all_jobs.sort(key=lambda j: (j.priority, j.created_at))
                self._worker.jobs_loaded.emit(
                    all_jobs, server_time or self._cache.last_server_time or ""
                )
            else:
                jobs, server_time = client.list_jobs(document_id=None)
                elapsed = time.time() - t0
                logger.info(
                    f"Fetch completed: mode=full, jobs={len(jobs)}, "
                    f"elapsed={elapsed:.2f}s"
                )
                self._worker.jobs_loaded.emit(jobs, server_time)

        except Exception as e:
            elapsed = time.time() - t0
            logger.error(
                f"Fetch failed: mode={mode}, elapsed={elapsed:.2f}s, error={e}",
                exc_info=True,
            )
            self._worker.jobs_error.emit(str(e))

    # ── Jobs loaded / error (main thread) ─────────────────────────────

    def _on_jobs_loaded(self, jobs: list, server_time: str = "") -> None:
        """Слот: список задач получен."""
        t0 = time.time()

        self._cache.log_status_changes(jobs)

        if self._poller.is_manual_refresh or not self._cache.last_server_time:
            # Полный fetch — id, которых сервер уже не отдаёт, можно убрать
            # из cleared-set: DELETE прошёл, держать их в snapshot больше
            # не нужно (set не разрастается).
            self._cache.prune_cleared({j.id for j in jobs})
            self._cache.replace_all(jobs, server_time)
            logger.debug(
                f"Jobs cache initialized with {len(self._cache)} jobs, "
                f"server_time={self._cache.last_server_time}"
            )

        merged_jobs = self._cache.merge_optimistic(jobs)

        self.jobs_updated.emit(merged_jobs)
        self.connection_status.emit("connected")

        save_snapshot(self._cache)
        logger.info(f"_on_jobs_loaded processed {len(merged_jobs)} jobs in {time.time() - t0:.2f}s")

        self._check_auto_download(merged_jobs)

        has_active = any(j.status in ("queued", "processing") for j in merged_jobs)
        self._poller.on_fetch_success(has_active)

    def _on_jobs_error(self, error_msg: str) -> None:
        """Слот: ошибка загрузки списка."""
        self.connection_status.emit("disconnected")
        self._poller.on_fetch_error(was_delta=self._poller.should_use_delta)

    # ── Job details ───────────────────────────────────────────────────

    def show_job_details(self, job_id: str) -> None:
        """Показать детальную информацию о задаче."""
        client = self._get_client()
        if client is None:
            return
        pdf_path = getattr(self.main_window, "_current_pdf_path", None)
        self._executor.submit(self._fetch_job_details_bg, client, job_id, pdf_path)

    def _fetch_job_details_bg(
        self, client: RemoteOCRClient, job_id: str, pdf_path: str | None
    ) -> None:
        """Фоновая загрузка деталей задачи."""
        try:
            job_details = client.get_job_details(job_id)
            if pdf_path:
                job_details["client_output_dir"] = str(Path(pdf_path).parent)
            self._worker.job_details_loaded.emit(job_details)
        except Exception as e:
            logger.error(f"Ошибка получения информации о задаче: {e}")
            self._worker.job_details_loaded.emit({"_error": str(e)})

    def _on_job_details_loaded(self, job_details: dict) -> None:
        """Слот: детали задачи загружены."""
        error = job_details.get("_error")
        if error:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self.main_window, "Ошибка", f"Не удалось получить информацию:\n{error}"
            )
            return

        from app.gui.job_details_dialog import JobDetailsDialog
        dialog = JobDetailsDialog(job_details, self.main_window)
        dialog.exec()

    # ── Auto-download candidate selection ─────────────────────────────

    def _check_auto_download(self, jobs: list) -> None:
        """Проверить и запустить авто-скачивание для текущего документа."""
        current_node_id = getattr(self.main_window, "_current_node_id", None)
        if not current_node_id:
            return

        has_active_for_node = any(
            j.status in ("queued", "processing")
            and getattr(j, "node_id", None) == current_node_id
            for j in jobs
        )
        if has_active_for_node:
            return

        latest_done = None
        for job in reversed(jobs):
            if (
                job.status in ("done", "partial")
                and getattr(job, "node_id", None) == current_node_id
                and not self._cache.is_downloaded(job.id)
                and not self._cache.is_downloading(job.id)
                and not self._cache.is_orphan(job.id)
            ):
                latest_done = job
                break

        if latest_done is None:
            return

        current_doc = getattr(self.main_window, "annotation_document", None)
        if current_doc:
            all_blocks = [
                b for p in current_doc.pages for b in p.blocks
            ]
            if all_blocks and all(b.ocr_text for b in all_blocks):
                self._cache.mark_downloaded(latest_done.id)
                return

        if not self._poller._panel_visible:
            from app.gui.toast import show_toast

            doc_name = latest_done.task_name or latest_done.document_name or ""
            if latest_done.status == "partial":
                toast_msg = f"OCR частично завершён: {doc_name}"
            else:
                toast_msg = f"OCR завершён: {doc_name}"
            show_toast(
                self.main_window,
                toast_msg,
                duration=5000,
            )
            logger.info(
                f"Задача {latest_done.id[:8]}... завершена ({latest_done.status}) "
                f"(панель скрыта), показано уведомление"
            )

        self.auto_download_result(latest_done.id)
