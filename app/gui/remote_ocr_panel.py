"""Панель для управления Remote OCR задачами"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.remote_ocr_download import DownloadMixin
from app.gui.remote_ocr_job_operations import JobOperationsMixin
from app.gui.remote_ocr_signals import WorkerSignals
from app.gui.utils import format_datetime_utc3

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class RemoteOCRPanel(JobOperationsMixin, DownloadMixin, QDockWidget):
    """Dock-панель для Remote OCR задач"""

    POLL_INTERVAL_PROCESSING = 15000   # 15 сек (было 5) - активные задачи
    POLL_INTERVAL_IDLE = 60000         # 60 сек (было 30) - нет активных задач
    POLL_INTERVAL_ERROR = 120000       # 120 сек (было 60) - при ошибках

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__("Remote OCR Jobs", parent)
        self.setObjectName("RemoteOCRPanel")
        self.main_window = main_window
        self._client = None
        self._current_document_id = None
        self._last_output_dir = None
        self._last_engine = None
        self._has_active_jobs = False
        self._consecutive_errors = 0
        self._is_fetching = False
        self._is_manual_refresh = False

        self._executor = ThreadPoolExecutor(max_workers=2)
        self._signals = WorkerSignals()
        self._signals.jobs_loaded.connect(self._on_jobs_loaded)
        self._signals.jobs_error.connect(self._on_jobs_error)
        self._signals.job_uploading.connect(self._on_job_uploading)
        self._signals.job_created.connect(self._on_job_created)
        self._signals.job_create_error.connect(self._on_job_create_error)
        self._signals.download_started.connect(self._on_download_started)
        self._signals.download_progress.connect(self._on_download_progress)
        self._signals.download_finished.connect(self._on_download_finished)
        self._signals.download_error.connect(self._on_download_error)
        self._signals.rerun_created.connect(self._on_rerun_created)
        self._signals.rerun_error.connect(self._on_rerun_error)
        self._signals.rerun_no_changes.connect(self._on_rerun_no_changes)

        self._download_dialog: Optional[QProgressDialog] = None
        self._downloaded_jobs: set = set()  # Уже скачанные задачи
        self._optimistic_jobs: dict = {}  # Оптимистично добавленные задачи {job_id: (JobInfo, timestamp)}
        self._last_server_time: Optional[str] = None  # Для incremental polling
        self._jobs_cache: dict = {}  # Кеш задач для incremental обновления {job_id: JobInfo}

        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        """Настроить UI панели"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Задачи:"))

        self.status_label = QLabel("🔴 Не подключено")
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)

        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setMaximumWidth(30)
        self.refresh_btn.setToolTip("Обновить список")
        self.refresh_btn.clicked.connect(lambda: self._refresh_jobs(manual=True))
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)

        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(7)
        self.jobs_table.setHorizontalHeaderLabels(
            ["№", "Наименование", "Время начала", "Статус", "Прогресс", "Детали", "Действия"]
        )

        header = self.jobs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        self.jobs_table.setSortingEnabled(True)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.jobs_table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.jobs_table)

        self.setWidget(widget)
        self.setMinimumWidth(520)
        self.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )

    def _setup_timer(self):
        """Настроить таймер для автообновления"""
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_jobs)
        # Запускаем таймер сразу с idle интервалом
        self.refresh_timer.start(self.POLL_INTERVAL_IDLE)
        logger.info(
            f"Таймер автообновления Remote OCR запущен: {self.POLL_INTERVAL_IDLE}ms"
        )
        # Делаем первое обновление сразу
        self._refresh_jobs(manual=False)

    def _get_client(self):
        """Получить или создать клиент"""
        if self._client is None:
            try:
                import os

                from app.remote_ocr_client import RemoteOCRClient

                base_url = os.getenv("REMOTE_OCR_BASE_URL", "http://localhost:8000")
                api_key = os.getenv("REMOTE_OCR_API_KEY")
                logger.info(
                    f"Creating RemoteOCRClient: REMOTE_OCR_BASE_URL={base_url}, API_KEY={'set' if api_key else 'NOT SET'}"
                )
                self._client = RemoteOCRClient()
                logger.info(f"Client created: base_url={self._client.base_url}")
            except Exception as e:
                logger.error(f"Ошибка создания клиента: {e}", exc_info=True)
                return None
        return self._client

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
            self._signals.jobs_error.emit("Ошибка клиента")
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
            self._signals.jobs_error.emit(str(e))

    def _fetch_changes_bg(self):
        """Фоновая загрузка только изменений (incremental polling)"""
        client = self._get_client()
        if client is None:
            self._signals.jobs_error.emit("Ошибка клиента")
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
            self._signals.jobs_error.emit(str(e))

    def _on_jobs_loaded(self, jobs):
        """Слот: список задач получен"""
        from datetime import datetime

        self._is_fetching = False

        # При первой полной загрузке (ручное обновление или первый запуск)
        # инициализируем кеш и server_time
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
                # Задача уже в списке от сервера - удаляем из оптимистичного списка
                logger.info(f"Задача {job_id[:8]}... найдена в ответе сервера, удаляем из оптимистичного списка")
                self._optimistic_jobs.pop(job_id, None)
            elif current_time - timestamp > 60:
                # Задача висит в оптимистичном списке более минуты - удаляем (таймаут)
                logger.warning(f"Задача {job_id[:8]}... в оптимистичном списке более минуты, удаляем (таймаут)")
                self._optimistic_jobs.pop(job_id, None)
            else:
                # Задачи ещё нет на сервере - добавляем в начало списка
                logger.debug(f"Задача {job_id[:8]}... ещё не на сервере, добавляем оптимистично")
                merged_jobs.insert(0, job_info)

        self._update_table(merged_jobs)
        self.status_label.setText("🟢 Подключено")
        self._consecutive_errors = 0

        self._has_active_jobs = any(j.status in ("queued", "processing") for j in merged_jobs)
        new_interval = (
            self.POLL_INTERVAL_PROCESSING
            if self._has_active_jobs
            else self.POLL_INTERVAL_IDLE
        )
        if self.refresh_timer.interval() != new_interval:
            self.refresh_timer.setInterval(new_interval)

    def _on_jobs_error(self, error_msg: str):
        """Слот: ошибка загрузки списка"""
        self._is_fetching = False
        self.status_label.setText("🔴 Сервер недоступен")
        self._consecutive_errors += 1
        
        # Уведомляем ConnectionManager о проблеме
        main_window = self.main_window
        if hasattr(main_window, 'connection_manager') and main_window.connection_manager:
            main_window.connection_manager.mark_error(error_msg)
        
        backoff_interval = min(
            self.POLL_INTERVAL_ERROR * (2 ** min(self._consecutive_errors - 1, 3)),
            180000,
        )
        if self.refresh_timer.interval() != backoff_interval:
            self.refresh_timer.setInterval(backoff_interval)

    def _update_table(self, jobs):
        """Обновить таблицу задач"""
        self.jobs_table.setSortingEnabled(False)
        self.jobs_table.setRowCount(0)

        # Авто-скачивание результата для текущего документа (только один раз)
        current_node_id = getattr(self.main_window, "_current_node_id", None)
        if current_node_id:
            for job in jobs:
                if (
                    job.status == "done"
                    and getattr(job, "node_id", None) == current_node_id
                ):
                    if job.id not in self._downloaded_jobs:
                        self._auto_download_result(job.id)
                    break  # Только последняя done задача для текущего документа

        for idx, job in enumerate(jobs, start=1):
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)

            num_item = QTableWidgetItem(str(idx))
            num_item.setData(Qt.UserRole, job.id)
            self.jobs_table.setItem(row, 0, num_item)

            display_name = job.task_name if job.task_name else job.document_name
            self.jobs_table.setItem(row, 1, QTableWidgetItem(display_name))

            created_at_str = format_datetime_utc3(job.created_at)
            created_item = QTableWidgetItem(created_at_str)
            created_item.setData(Qt.UserRole, job.created_at)
            self.jobs_table.setItem(row, 2, created_item)

            status_text = {
                "uploading": "⬆️ Загрузка...",
                "draft": "📝 Черновик",
                "queued": "⏳ В очереди",
                "processing": "🔄 Обработка",
                "done": "✅ Готово",
                "error": "❌ Ошибка",
                "paused": "⏸️ Пауза",
            }.get(job.status, job.status)

            status_item = QTableWidgetItem(status_text)
            if job.error_message:
                status_item.setToolTip(job.error_message)
            self.jobs_table.setItem(row, 3, status_item)

            progress_text = f"{int(job.progress * 100)}%"
            progress_item = QTableWidgetItem(progress_text)
            progress_item.setData(Qt.UserRole, job.progress)
            self.jobs_table.setItem(row, 4, progress_item)

            status_msg = job.status_message or ""
            status_msg_item = QTableWidgetItem(status_msg)
            self.jobs_table.setItem(row, 5, status_msg_item)

            actions_widget = self._create_actions_widget(job)
            self.jobs_table.setCellWidget(row, 6, actions_widget)

        self.jobs_table.setSortingEnabled(True)

    def _add_job_to_table(self, job, at_top: bool = False):
        """Добавить одну задачу в таблицу (для оптимистичного обновления)"""
        logger.info(
            f"_add_job_to_table: job_id={job.id}, at_top={at_top}, current_rows={self.jobs_table.rowCount()}"
        )

        self.jobs_table.setSortingEnabled(False)

        row = 0 if at_top else self.jobs_table.rowCount()
        self.jobs_table.insertRow(row)

        num_item = QTableWidgetItem("1" if at_top else str(self.jobs_table.rowCount()))
        num_item.setData(Qt.UserRole, job.id)
        self.jobs_table.setItem(row, 0, num_item)

        display_name = job.task_name if job.task_name else job.document_name
        self.jobs_table.setItem(row, 1, QTableWidgetItem(display_name))

        created_at_str = (
            format_datetime_utc3(job.created_at) if job.created_at else "Только что"
        )
        created_item = QTableWidgetItem(created_at_str)
        created_item.setData(Qt.UserRole, job.created_at)
        self.jobs_table.setItem(row, 2, created_item)

        status_text = {
            "uploading": "⬆️ Загрузка...",
            "draft": "📝 Черновик",
            "queued": "⏳ В очереди",
            "processing": "🔄 Обработка",
            "done": "✅ Готово",
            "error": "❌ Ошибка",
            "paused": "⏸️ Пауза",
        }.get(job.status, job.status)
        self.jobs_table.setItem(row, 3, QTableWidgetItem(status_text))

        progress_text = f"{int(job.progress * 100)}%"
        progress_item = QTableWidgetItem(progress_text)
        progress_item.setData(Qt.UserRole, job.progress)
        self.jobs_table.setItem(row, 4, progress_item)

        status_msg = job.status_message or ""
        status_msg_item = QTableWidgetItem(status_msg)
        self.jobs_table.setItem(row, 5, status_msg_item)

        actions_widget = self._create_actions_widget(job)
        self.jobs_table.setCellWidget(row, 6, actions_widget)

        self.jobs_table.setSortingEnabled(True)

        logger.info(
            f"Задача добавлена в таблицу: row={row}, name={display_name}, status={job.status}, total_rows={self.jobs_table.rowCount()}"
        )

    def _replace_job_in_table(self, old_job_id: str, new_job):
        """Заменить временную задачу на реальную в таблице"""
        # Ищем строку с временным job_id
        for row in range(self.jobs_table.rowCount()):
            item = self.jobs_table.item(row, 0)
            if item and item.data(Qt.UserRole) == old_job_id:
                logger.info(f"Найдена временная задача в строке {row}, заменяем на {new_job.id}")

                # Обновляем данные в строке
                item.setData(Qt.UserRole, new_job.id)

                # Обновляем название
                display_name = new_job.task_name if new_job.task_name else new_job.document_name
                self.jobs_table.item(row, 1).setText(display_name)

                # Обновляем время
                created_at_str = format_datetime_utc3(new_job.created_at) if new_job.created_at else "Только что"
                self.jobs_table.item(row, 2).setText(created_at_str)

                # Обновляем статус
                status_text = {
                    "uploading": "⬆️ Загрузка...",
                    "draft": "📝 Черновик",
                    "queued": "⏳ В очереди",
                    "processing": "🔄 Обработка",
                    "done": "✅ Готово",
                    "error": "❌ Ошибка",
                    "paused": "⏸️ Пауза",
                }.get(new_job.status, new_job.status)
                self.jobs_table.item(row, 3).setText(status_text)

                # Обновляем прогресс
                progress_text = f"{int(new_job.progress * 100)}%"
                self.jobs_table.item(row, 4).setText(progress_text)

                # Обновляем сообщение о статусе
                status_msg = new_job.status_message or ""
                self.jobs_table.item(row, 5).setText(status_msg)

                # Заменяем виджет действий
                actions_widget = self._create_actions_widget(new_job)
                self.jobs_table.setCellWidget(row, 6, actions_widget)

                logger.info(f"Задача заменена: {old_job_id} -> {new_job.id}")
                return

        # Если не нашли - добавляем как новую
        logger.warning(f"Временная задача {old_job_id} не найдена в таблице, добавляем как новую")
        self._add_job_to_table(new_job, at_top=True)

    def _create_actions_widget(self, job) -> QWidget:
        """Создать виджет с кнопками действий для задачи"""
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(1, 1, 1, 1)
        actions_layout.setSpacing(2)

        rerun_btn = QPushButton("🔄")
        rerun_btn.setToolTip("Повторное распознавание")
        rerun_btn.setFixedSize(26, 26)
        rerun_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; border: 1px solid #1e8449; border-radius: 4px; } QPushButton:hover { background-color: #1e8449; }"
        )
        rerun_btn.clicked.connect(lambda checked, jid=job.id: self._rerun_job(jid))
        actions_layout.addWidget(rerun_btn)

        if job.status in ("queued", "processing"):
            pause_btn = QPushButton("⏸️")
            pause_btn.setToolTip("Поставить на паузу")
            pause_btn.setFixedSize(26, 26)
            pause_btn.clicked.connect(lambda checked, jid=job.id: self._pause_job(jid))
            actions_layout.addWidget(pause_btn)
        elif job.status == "paused":
            resume_btn = QPushButton("▶️")
            resume_btn.setToolTip("Возобновить")
            resume_btn.setFixedSize(26, 26)
            resume_btn.clicked.connect(
                lambda checked, jid=job.id: self._resume_job(jid)
            )
            actions_layout.addWidget(resume_btn)

        info_btn = QPushButton("ℹ️")
        info_btn.setToolTip("Информация о задаче")
        info_btn.setFixedSize(26, 26)
        info_btn.setStyleSheet(
            "QPushButton { background-color: #7f8c8d; border: 1px solid #636e72; border-radius: 4px; } QPushButton:hover { background-color: #636e72; }"
        )
        info_btn.clicked.connect(
            lambda checked, jid=job.id: self._show_job_details(jid)
        )
        actions_layout.addWidget(info_btn)

        delete_btn = QPushButton("🗑️")
        delete_btn.setToolTip("Удалить задачу")
        delete_btn.setFixedSize(26, 26)
        delete_btn.clicked.connect(lambda checked, jid=job.id: self._delete_job(jid))
        actions_layout.addWidget(delete_btn)

        actions_layout.addStretch()
        return actions_widget

    def _on_job_uploading(self, job_info):
        """Слот: задача начала загружаться — немедленное отображение в UI"""
        logger.info(
            f"Обработка job_uploading signal: temp_id={job_info.id}, status={job_info.status}"
        )

        # Добавляем временную задачу в оптимистичный список
        self._optimistic_jobs[job_info.id] = (job_info, time.time())
        logger.info(f"Временная задача добавлена в оптимистичный список: {job_info.id}")

        # Немедленно добавляем в таблицу
        self._add_job_to_table(job_info, at_top=True)
        logger.info(f"Временная задача добавлена в таблицу, строк={self.jobs_table.rowCount()}")

    def _on_job_created(self, job_info):
        """Слот: задача создана на сервере — заменяем временную на реальную"""
        logger.info(
            f"Обработка job_created signal: job_id={job_info.id}, status={job_info.status}"
        )
        from app.gui.toast import show_toast

        show_toast(self, f"Задача создана: {job_info.id[:8]}...", duration=2500)

        # Получаем временный ID для замены
        temp_job_id = getattr(job_info, "_temp_job_id", None)

        # Удаляем временную задачу из оптимистичного списка
        if temp_job_id and temp_job_id in self._optimistic_jobs:
            self._optimistic_jobs.pop(temp_job_id, None)
            logger.info(f"Удалена временная задача из оптимистичного списка: {temp_job_id}")

        # Добавляем реальную задачу в оптимистичный список
        self._optimistic_jobs[job_info.id] = (job_info, time.time())
        logger.info(f"Реальная задача добавлена в оптимистичный список: {job_info.id}")

        # Устанавливаем быстрый интервал обновления для скорейшей синхронизации
        if self.refresh_timer.interval() > 2000:
            self.refresh_timer.setInterval(2000)
            logger.info("Установлен быстрый интервал обновления: 2000ms")

        # Заменяем временную задачу на реальную в таблице
        if temp_job_id:
            self._replace_job_in_table(temp_job_id, job_info)
        else:
            # Fallback: просто добавляем в таблицу
            self._add_job_to_table(job_info, at_top=True)
        logger.info(f"Задача обновлена в таблице, строк={self.jobs_table.rowCount()}")

    def _on_job_create_error(self, error_type: str, message: str):
        """Слот: ошибка создания задачи"""
        # Удаляем временные задачи (uploading) из таблицы и оптимистичного списка
        uploading_ids = [
            job_id for job_id, (job_info, _) in self._optimistic_jobs.items()
            if job_info.status == "uploading"
        ]
        for job_id in uploading_ids:
            self._optimistic_jobs.pop(job_id, None)
            self._remove_job_from_table(job_id)

        titles = {
            "auth": "Ошибка авторизации",
            "size": "Файл слишком большой",
            "server": "Ошибка сервера",
            "generic": "Ошибка",
        }
        QMessageBox.critical(self, titles.get(error_type, "Ошибка"), message)

    def _remove_job_from_table(self, job_id: str):
        """Удалить задачу из таблицы по ID"""
        for row in range(self.jobs_table.rowCount()):
            item = self.jobs_table.item(row, 0)
            if item and item.data(Qt.UserRole) == job_id:
                self.jobs_table.removeRow(row)
                logger.info(f"Задача {job_id} удалена из таблицы")
                return

    def _get_selected_blocks(self):
        """Получить все блоки для OCR"""
        blocks = []
        if self.main_window.annotation_document:
            for page in self.main_window.annotation_document.pages:
                if page.blocks:
                    blocks.extend(page.blocks)

        self._attach_prompts_to_blocks(blocks)
        return blocks

    def _attach_prompts_to_blocks(self, blocks):
        """Промпты берутся из категорий в Supabase на стороне сервера"""
        # Промпты теперь загружаются на сервере из image_categories в Supabase
        pass

    def _on_download_started(self, job_id: str, total_files: int):
        """Слот: начало скачивания"""
        self._download_dialog = QProgressDialog(
            f"Скачивание файлов задачи {job_id[:8]}...", None, 0, total_files, self
        )
        self._download_dialog.setWindowTitle("Загрузка результатов")
        self._download_dialog.setWindowModality(Qt.WindowModal)
        self._download_dialog.setMinimumDuration(0)
        self._download_dialog.setValue(0)
        self._download_dialog.show()

    def _on_download_progress(self, job_id: str, current: int, filename: str):
        """Слот: прогресс скачивания"""
        dialog = self._download_dialog  # Локальная ссылка для thread safety
        if dialog:
            dialog.setValue(current)
            dialog.setLabelText(f"Скачивание: {filename}")

    def _on_download_finished(self, job_id: str, extract_dir: str):
        """Слот: скачивание завершено - перезагрузить аннотацию в GUI"""
        dialog = self._download_dialog  # Локальная ссылка для thread safety
        if dialog:
            dialog.close()
            self._download_dialog = None

        # Помечаем задачу как скачанную
        self._downloaded_jobs.add(job_id)

        # Перезагружаем аннотацию из скачанного файла
        self._reload_annotation_from_result(extract_dir)

        # Обновляем дерево проектов
        self._refresh_document_in_tree()

        from app.gui.toast import show_toast

        show_toast(self.main_window, f"OCR завершён, аннотация обновлена")

    def _refresh_document_in_tree(self):
        """Обновить узел документа в дереве проектов"""
        node_id = getattr(self.main_window, "_current_node_id", None)
        if not node_id:
            return

        if not hasattr(self.main_window, "project_tree_widget"):
            return

        tree = self.main_window.project_tree_widget
        item = tree._node_map.get(node_id)
        if not item:
            return

        node = item.data(0, Qt.UserRole)
        if not node:
            return

        # Обновляем отображение элемента (документы не имеют дочерних узлов)
        tree._start_sync_check()
        logger.info(f"Refreshed document in tree: {node_id}")

    def _reload_annotation_from_result(self, extract_dir: str):
        """Обновить ocr_text в блоках из результата OCR, сохраняя оригинальную геометрию"""
        try:
            pdf_path = getattr(self.main_window, "_current_pdf_path", None)
            if not pdf_path:
                return

            pdf_stem = Path(pdf_path).stem
            ann_path = Path(extract_dir) / f"{pdf_stem}_annotation.json"

            if not ann_path.exists():
                logger.warning(f"Файл аннотации не найден: {ann_path}")
                return

            from rd_core.annotation_io import AnnotationIO

            loaded_doc, result = AnnotationIO.load_and_migrate(str(ann_path))

            if not result.success or not loaded_doc:
                logger.warning(f"Не удалось загрузить OCR результат: {result.errors}")
                return

            current_doc = self.main_window.annotation_document
            if not current_doc:
                return

            # Собираем ocr_text по ID блоков из результата OCR
            ocr_results = {}
            for page in loaded_doc.pages:
                for block in page.blocks:
                    if block.ocr_text:
                        ocr_results[block.id] = block.ocr_text

            # Обновляем только ocr_text в существующих блоках
            updated_count = 0
            for page in current_doc.pages:
                for block in page.blocks:
                    if block.id in ocr_results:
                        block.ocr_text = ocr_results[block.id]
                        updated_count += 1

            self.main_window._render_current_page()
            if (
                hasattr(self.main_window, "blocks_tree_manager")
                and self.main_window.blocks_tree_manager
            ):
                self.main_window.blocks_tree_manager.update_blocks_tree()

            # Триггерим авто-сохранение с обновлёнными ocr_text
            if updated_count > 0:
                self.main_window._auto_save_annotation()

            # Перезагружаем OCR result file для preview
            if hasattr(self.main_window, "_load_ocr_result_file"):
                self.main_window._load_ocr_result_file()

            logger.info(f"OCR результаты применены: {updated_count} блоков обновлено")
        except Exception as e:
            logger.error(f"Ошибка применения OCR результатов: {e}")

    def _on_download_error(self, job_id: str, error_msg: str):
        """Слот: ошибка скачивания"""
        dialog = self._download_dialog  # Локальная ссылка для thread safety
        if dialog:
            dialog.close()
            self._download_dialog = None

        QMessageBox.critical(
            self, "Ошибка загрузки", f"Не удалось скачать файлы:\n{error_msg}"
        )

    def _on_rerun_created(self, old_job_id: str, new_job_info):
        """Слот: повторное распознавание создано"""
        from app.gui.toast import show_toast

        if new_job_info:
            show_toast(
                self, f"Задача пересоздана: {new_job_info.id[:8]}...", duration=2500
            )
        else:
            show_toast(self, f"Задача перезапущена: {old_job_id[:8]}...", duration=2500)
        self._refresh_jobs(manual=True)

    def _on_rerun_error(self, job_id: str, error_msg: str):
        """Слот: ошибка повторного распознавания"""
        QMessageBox.critical(
            self, "Ошибка", f"Не удалось повторить распознавание:\n{error_msg}"
        )

    def _on_rerun_no_changes(self, job_id: str):
        """Слот: блоки не изменились"""
        QMessageBox.information(
            self,
            "Без изменений",
            "Блоки не изменились.\nФайл уже был распознан с текущей аннотацией.",
        )

    def showEvent(self, event):
        """При показе панели обновляем список"""
        super().showEvent(event)
        self._refresh_jobs(manual=True)
        self.refresh_timer.start(self.POLL_INTERVAL_IDLE)

    def hideEvent(self, event):
        """При скрытии останавливаем таймер"""
        super().hideEvent(event)
        self.refresh_timer.stop()

    def closeEvent(self, event):
        """Освобождаем ресурсы"""
        self._executor.shutdown(wait=False)
        super().closeEvent(event)
