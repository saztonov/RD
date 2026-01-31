"""Панель для управления Remote OCR задачами"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
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
    QVBoxLayout,
    QWidget,
)

from app.gui.remote_ocr.download_mixin import DownloadMixin
from app.gui.remote_ocr.job_operations import JobOperationsMixin
from app.gui.remote_ocr.polling_controller import PollingControllerMixin
from app.gui.remote_ocr.result_handler import ResultHandlerMixin
from app.gui.remote_ocr.signals import WorkerSignals
from app.gui.remote_ocr.table_manager import TableManagerMixin

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class RemoteOCRPanel(
    JobOperationsMixin,
    DownloadMixin,
    PollingControllerMixin,
    TableManagerMixin,
    ResultHandlerMixin,
    QDockWidget,
):
    """Dock-панель для Remote OCR задач"""

    POLL_INTERVAL_PROCESSING = 15000   # 15 сек - активные задачи
    POLL_INTERVAL_IDLE = 60000         # 60 сек - нет активных задач
    POLL_INTERVAL_ERROR = 120000       # 120 сек - при ошибках

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
        self._connect_signals()

        self._download_dialog: Optional[QProgressDialog] = None
        self._downloaded_jobs: set = set()
        self._optimistic_jobs: dict = {}
        self._last_server_time: Optional[str] = None
        self._jobs_cache: dict = {}
        self._force_full_refresh: bool = False

        self._setup_ui()
        self._setup_timer()

    def _connect_signals(self):
        """Подключить сигналы"""
        self._signals.jobs_loaded.connect(self._on_jobs_loaded)
        self._signals.jobs_error.connect(self._on_jobs_error)
        self._signals.job_uploading.connect(self._on_job_uploading)
        self._signals.job_created.connect(self._on_job_created)
        self._signals.job_create_error.connect(self._on_job_create_error)
        self._signals.download_started.connect(self._on_download_started)
        self._signals.download_progress.connect(self._on_download_progress)
        self._signals.download_finished.connect(self._on_download_finished)
        self._signals.download_error.connect(self._on_download_error)

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

        self.clear_all_btn = QPushButton("🗑️")
        self.clear_all_btn.setMaximumWidth(30)
        self.clear_all_btn.setToolTip("Очистить все задачи")
        self.clear_all_btn.clicked.connect(self._clear_all_jobs)
        header_layout.addWidget(self.clear_all_btn)

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
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        # Default widths
        header.resizeSection(0, 35)   # №
        header.resizeSection(1, 150)  # Наименование
        header.resizeSection(2, 120)  # Время начала
        header.resizeSection(3, 100)  # Статус
        header.resizeSection(4, 70)   # Прогресс
        header.resizeSection(5, 150)  # Детали
        header.resizeSection(6, 70)   # Действия

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
        self.refresh_timer.start(self.POLL_INTERVAL_IDLE)
        logger.info(
            f"Таймер автообновления Remote OCR запущен: {self.POLL_INTERVAL_IDLE}ms"
        )
        self._refresh_jobs(manual=False)

    def _get_client(self):
        """Получить или создать клиент"""
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
        pass

    def _on_job_uploading(self, job_info):
        """Слот: задача начала загружаться"""
        logger.info(
            f"Обработка job_uploading signal: temp_id={job_info.id}, status={job_info.status}"
        )

        self._optimistic_jobs[job_info.id] = (job_info, time.time())
        logger.info(f"Временная задача добавлена в оптимистичный список: {job_info.id}")

        self._add_job_to_table(job_info, at_top=True)
        logger.info(
            f"Временная задача добавлена в таблицу, строк={self.jobs_table.rowCount()}"
        )

    def _on_job_created(self, job_info):
        """Слот: задача создана на сервере"""
        logger.info(
            f"Обработка job_created signal: job_id={job_info.id}, status={job_info.status}"
        )
        from app.gui.toast import show_toast

        show_toast(self, f"Задача создана: {job_info.id[:8]}...", duration=2500)

        temp_job_id = getattr(job_info, "_temp_job_id", None)

        if temp_job_id and temp_job_id in self._optimistic_jobs:
            self._optimistic_jobs.pop(temp_job_id, None)
            logger.info(f"Удалена временная задача из оптимистичного списка: {temp_job_id}")

        self._optimistic_jobs[job_info.id] = (job_info, time.time())
        logger.info(f"Реальная задача добавлена в оптимистичный список: {job_info.id}")

        if self.refresh_timer.interval() > 2000:
            self.refresh_timer.setInterval(2000)
            logger.info("Установлен быстрый интервал обновления: 2000ms")

        if temp_job_id:
            self._replace_job_in_table(temp_job_id, job_info)
        else:
            self._add_job_to_table(job_info, at_top=True)
        logger.info(
            f"Задача обновлена в таблице, строк={self.jobs_table.rowCount()}"
        )

    def _on_job_create_error(self, error_type: str, message: str):
        """Слот: ошибка создания задачи"""
        uploading_ids = [
            job_id
            for job_id, (job_info, _) in self._optimistic_jobs.items()
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
        dialog = self._download_dialog
        if dialog:
            dialog.setValue(current)
            dialog.setLabelText(f"Скачивание: {filename}")

    def _on_download_finished(self, job_id: str, extract_dir: str):
        """Слот: скачивание завершено"""
        dialog = self._download_dialog
        if dialog:
            dialog.close()
            self._download_dialog = None

        self._downloaded_jobs.add(job_id)

        self._reload_annotation_from_result(extract_dir)
        self._refresh_document_in_tree()

        from app.gui.toast import show_toast

        show_toast(self.main_window, "OCR завершён, аннотация обновлена")

    def _on_download_error(self, job_id: str, error_msg: str):
        """Слот: ошибка скачивания"""
        dialog = self._download_dialog
        if dialog:
            dialog.close()
            self._download_dialog = None

        QMessageBox.critical(
            self, "Ошибка загрузки", f"Не удалось скачать файлы:\n{error_msg}"
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
