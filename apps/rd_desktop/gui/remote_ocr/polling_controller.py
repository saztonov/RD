"""Контроллер polling для Remote OCR"""

import logging
import time
from datetime import datetime

from apps.rd_desktop.gui.connection_manager import is_network_error

logger = logging.getLogger(__name__)


class PollingControllerMixin:
    """Миксин для управления polling задач"""

    def _refresh_jobs(self, manual: bool = False):
        """Обновить список задач"""
        if self._is_fetching:
            return
        self._is_fetching = True
        self._is_manual_refresh = manual

        if manual:
            self.status_label.setText("🔄 Загрузка...")
            # При ручном обновлении - полный список
            self._executor.submit(self._fetch_jobs_bg)
        elif self._last_server_time and self._jobs_cache:
            # Incremental polling - только изменения
            self._executor.submit(self._fetch_changes_bg)
        else:
            # Первая загрузка - полный список
            self._executor.submit(self._fetch_jobs_bg)

    def _fetch_jobs_bg(self):
        """Фоновая загрузка полного списка задач"""
        client = self._get_client()
        if client is None:
            self._signals.jobs_error.emit("Ошибка клиента", False)
            return
        try:
            logger.debug(f"Fetching full jobs list from {client.base_url}")
            jobs = client.list_jobs(document_id=None)
            logger.debug(f"Fetched {len(jobs)} jobs")
            self._signals.jobs_loaded.emit(jobs)
        except Exception as e:
            logger.error(
                f"Ошибка получения списка задач от {client.base_url}: {e}",
                exc_info=True,
            )
            self._signals.jobs_error.emit(str(e), is_network_error(e))

    def _fetch_changes_bg(self):
        """Фоновая загрузка только изменений (incremental polling)"""
        client = self._get_client()
        if client is None:
            self._signals.jobs_error.emit("Ошибка клиента", False)
            return
        try:
            logger.debug(f"Fetching job changes since {self._last_server_time}")
            changed_jobs, server_time = client.get_jobs_changes(self._last_server_time)
            logger.debug(f"Fetched {len(changed_jobs)} changed jobs")

            # Обновляем кеш изменёнными задачами
            for job in changed_jobs:
                self._jobs_cache[job.id] = job

            # Обновляем server_time
            if server_time:
                self._last_server_time = server_time

            # Отправляем полный список из кеша
            all_jobs = list(self._jobs_cache.values())
            # Сортируем по времени создания (новые первыми)
            all_jobs.sort(key=lambda j: j.created_at, reverse=True)
            self._signals.jobs_loaded.emit(all_jobs)
        except Exception as e:
            logger.error(f"Ошибка получения изменений: {e}", exc_info=True)
            # При ошибке incremental - пробуем полную загрузку
            self._last_server_time = None
            self._jobs_cache.clear()
            self._signals.jobs_error.emit(str(e), is_network_error(e))

    def _on_jobs_loaded(self, jobs):
        """Слот: список задач получен"""
        self._is_fetching = False

        # При первой полной загрузке инициализируем кеш и server_time
        if self._is_manual_refresh or not self._last_server_time:
            self._jobs_cache = {j.id: j for j in jobs}
            self._last_server_time = datetime.utcnow().isoformat()
            logger.debug(f"Jobs cache initialized with {len(self._jobs_cache)} jobs")

        # Добавляем оптимистично добавленные задачи, которых ещё нет в ответе сервера
        jobs_ids = {j.id for j in jobs}
        merged_jobs = list(jobs)
        current_time = time.time()

        for job_id, (job_info, timestamp) in list(self._optimistic_jobs.items()):
            if job_id in jobs_ids:
                logger.info(
                    f"Задача {job_id[:8]}... найдена в ответе сервера, "
                    "удаляем из оптимистичного списка"
                )
                self._optimistic_jobs.pop(job_id, None)
            elif current_time - timestamp > 60:
                logger.warning(
                    f"Задача {job_id[:8]}... в оптимистичном списке более минуты, "
                    "удаляем (таймаут)"
                )
                self._optimistic_jobs.pop(job_id, None)
            else:
                logger.debug(
                    f"Задача {job_id[:8]}... ещё не на сервере, добавляем оптимистично"
                )
                merged_jobs.insert(0, job_info)

        self._update_table(merged_jobs)
        self.status_label.setText("🟢 Подключено")
        self._consecutive_errors = 0

        self._has_active_jobs = any(
            j.status in ("queued", "processing") for j in merged_jobs
        )
        new_interval = (
            self.POLL_INTERVAL_PROCESSING
            if self._has_active_jobs
            else self.POLL_INTERVAL_IDLE
        )
        if self.refresh_timer.interval() != new_interval:
            self.refresh_timer.setInterval(new_interval)

    def _on_jobs_error(self, error_msg: str, is_network_err: bool = True):
        """Слот: ошибка загрузки списка"""
        self._is_fetching = False
        self._consecutive_errors += 1

        # Уведомляем ConnectionManager только о сетевых ошибках
        # HTTP 500 означает что сервер доступен, но есть баг на эндпоинте
        if is_network_err:
            self.status_label.setText("🔴 Сервер недоступен")
            main_window = self.main_window
            if hasattr(main_window, "connection_manager") and main_window.connection_manager:
                main_window.connection_manager.mark_error(error_msg)
        else:
            # Серверная ошибка (5xx) - сервер доступен, но временная проблема
            self.status_label.setText("🟡 Ошибка сервера")
            logger.warning(f"Серверная ошибка (не сетевая): {error_msg}")

        backoff_interval = min(
            self.POLL_INTERVAL_ERROR * (2 ** min(self._consecutive_errors - 1, 3)),
            180000,
        )
        if self.refresh_timer.interval() != backoff_interval:
            self.refresh_timer.setInterval(backoff_interval)
