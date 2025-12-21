"""Панель для управления Remote OCR задачами"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDockWidget, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QLabel, QProgressDialog
)

from app.gui.remote_ocr_signals import WorkerSignals
from app.gui.remote_ocr_download import DownloadMixin
from app.gui.remote_ocr_job_operations import JobOperationsMixin
from app.gui.remote_ocr_editor import EditorMixin

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class RemoteOCRPanel(EditorMixin, JobOperationsMixin, DownloadMixin, QDockWidget):
    """Dock-панель для Remote OCR задач"""
    
    POLL_INTERVAL_PROCESSING = 5000
    POLL_INTERVAL_IDLE = 30000
    POLL_INTERVAL_ERROR = 60000
    
    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__("Remote OCR Jobs", parent)
        self.setObjectName("RemoteOCRPanel")
        self.main_window = main_window
        self._client = None
        self._current_document_id = None
        self._last_output_dir = None
        self._last_engine = None
        self._job_output_dirs = {}
        self._config_file = Path.home() / ".rd" / "remote_ocr_jobs.json"
        self._has_active_jobs = False
        self._consecutive_errors = 0
        self._is_fetching = False
        self._is_manual_refresh = False
        
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._signals = WorkerSignals()
        self._signals.jobs_loaded.connect(self._on_jobs_loaded)
        self._signals.jobs_error.connect(self._on_jobs_error)
        self._signals.job_created.connect(self._on_job_created)
        self._signals.job_create_error.connect(self._on_job_create_error)
        self._signals.download_started.connect(self._on_download_started)
        self._signals.download_progress.connect(self._on_download_progress)
        self._signals.download_finished.connect(self._on_download_finished)
        self._signals.download_error.connect(self._on_download_error)
        self._signals.rerun_created.connect(self._on_rerun_created)
        self._signals.rerun_error.connect(self._on_rerun_error)
        
        self._download_dialog: Optional[QProgressDialog] = None
        self._pending_open_in_editor: Optional[str] = None
        
        self._load_job_mappings()
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
        self.jobs_table.setColumnCount(6)
        self.jobs_table.setHorizontalHeaderLabels(["№", "Наименование", "Время начала", "Статус", "Прогресс", "Действия"])
        
        header = self.jobs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        self.jobs_table.setSortingEnabled(True)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.jobs_table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.jobs_table)
        
        self.setWidget(widget)
        self.setMinimumWidth(520)
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
    
    def _setup_timer(self):
        """Настроить таймер для автообновления"""
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_jobs)
    
    def _load_job_mappings(self):
        """Загрузить сохранённые маппинги job_id -> output_dir"""
        try:
            if self._config_file.exists():
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    self._job_output_dirs = json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка загрузки маппингов задач: {e}")
            self._job_output_dirs = {}
    
    def _save_job_mappings(self):
        """Сохранить маппинги job_id -> output_dir"""
        try:
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._job_output_dirs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Ошибка сохранения маппингов задач: {e}")
    
    def _get_client(self):
        """Получить или создать клиент"""
        if self._client is None:
            try:
                from app.remote_ocr_client import RemoteOCRClient
                self._client = RemoteOCRClient()
            except Exception as e:
                logger.error(f"Ошибка создания клиента: {e}")
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
        
        self._executor.submit(self._fetch_jobs_bg)
    
    def _fetch_jobs_bg(self):
        """Фоновая загрузка списка задач"""
        client = self._get_client()
        if client is None:
            self._signals.jobs_error.emit("Ошибка клиента")
            return
        try:
            jobs = client.list_jobs(document_id=None)
            self._signals.jobs_loaded.emit(jobs)
        except Exception as e:
            logger.error(f"Ошибка получения списка задач: {e}")
            self._signals.jobs_error.emit(str(e))
    
    def _on_jobs_loaded(self, jobs):
        """Слот: список задач получен"""
        self._is_fetching = False
        self._update_table(jobs)
        self.status_label.setText("🟢 Подключено")
        self._consecutive_errors = 0
        
        self._has_active_jobs = any(j.status in ("queued", "processing") for j in jobs)
        new_interval = self.POLL_INTERVAL_PROCESSING if self._has_active_jobs else self.POLL_INTERVAL_IDLE
        if self.refresh_timer.interval() != new_interval:
            self.refresh_timer.setInterval(new_interval)
    
    def _on_jobs_error(self, error_msg: str):
        """Слот: ошибка загрузки списка"""
        self._is_fetching = False
        self.status_label.setText("🔴 Сервер недоступен")
        self._consecutive_errors += 1
        backoff_interval = min(self.POLL_INTERVAL_ERROR * (2 ** min(self._consecutive_errors - 1, 3)), 180000)
        if self.refresh_timer.interval() != backoff_interval:
            self.refresh_timer.setInterval(backoff_interval)
    
    def _update_table(self, jobs):
        """Обновить таблицу задач"""
        self.jobs_table.setSortingEnabled(False)
        self.jobs_table.setRowCount(0)
        
        for job in jobs:
            if job.status == "done" and job.id in self._job_output_dirs:
                extract_dir = Path(self._job_output_dirs[job.id])
                if not (extract_dir / "annotation.json").exists():
                    self._auto_download_result(job.id)
        
        for idx, job in enumerate(jobs, start=1):
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)
            
            num_item = QTableWidgetItem(str(idx))
            num_item.setData(Qt.UserRole, job.id)
            self.jobs_table.setItem(row, 0, num_item)
            
            display_name = job.task_name if job.task_name else job.document_name
            self.jobs_table.setItem(row, 1, QTableWidgetItem(display_name))
            
            created_at_str = self._format_datetime_utc3(job.created_at)
            created_item = QTableWidgetItem(created_at_str)
            created_item.setData(Qt.UserRole, job.created_at)
            self.jobs_table.setItem(row, 2, created_item)
            
            status_text = {
                "draft": "📝 Черновик",
                "queued": "⏳ В очереди",
                "processing": "🔄 Обработка",
                "done": "✅ Готово",
                "error": "❌ Ошибка",
                "paused": "⏸️ Пауза"
            }.get(job.status, job.status)
            
            status_item = QTableWidgetItem(status_text)
            if job.error_message:
                status_item.setToolTip(job.error_message)
            self.jobs_table.setItem(row, 3, status_item)
            
            progress_text = f"{int(job.progress * 100)}%"
            progress_item = QTableWidgetItem(progress_text)
            progress_item.setData(Qt.UserRole, job.progress)
            self.jobs_table.setItem(row, 4, progress_item)
            
            actions_widget = self._create_actions_widget(job)
            self.jobs_table.setCellWidget(row, 5, actions_widget)
        
        self.jobs_table.setSortingEnabled(True)
    
    def _create_actions_widget(self, job) -> QWidget:
        """Создать виджет с кнопками действий для задачи"""
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(1, 1, 1, 1)
        actions_layout.setSpacing(2)
        
        open_btn = QPushButton("✏️")
        open_btn.setToolTip("Открыть в редакторе")
        open_btn.setFixedSize(26, 26)
        open_btn.clicked.connect(lambda checked, jid=job.id: self._open_job_in_editor(jid))
        actions_layout.addWidget(open_btn)
        
        rerun_btn = QPushButton("🔁")
        rerun_btn.setToolTip("Повторное распознавание")
        rerun_btn.setFixedSize(26, 26)
        rerun_btn.setStyleSheet("QPushButton { background-color: #e67e22; border: 1px solid #d35400; border-radius: 4px; } QPushButton:hover { background-color: #d35400; }")
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
            resume_btn.clicked.connect(lambda checked, jid=job.id: self._resume_job(jid))
            actions_layout.addWidget(resume_btn)
        
        info_btn = QPushButton("ℹ️")
        info_btn.setToolTip("Информация о задаче")
        info_btn.setFixedSize(26, 26)
        info_btn.setStyleSheet("QPushButton { background-color: #7f8c8d; border: 1px solid #636e72; border-radius: 4px; } QPushButton:hover { background-color: #636e72; }")
        info_btn.clicked.connect(lambda checked, jid=job.id: self._show_job_details(jid))
        actions_layout.addWidget(info_btn)
        
        delete_btn = QPushButton("🗑️")
        delete_btn.setToolTip("Удалить задачу")
        delete_btn.setFixedSize(26, 26)
        delete_btn.clicked.connect(lambda checked, jid=job.id: self._delete_job(jid))
        actions_layout.addWidget(delete_btn)
        
        actions_layout.addStretch()
        return actions_widget

    def _on_job_created(self, job_info):
        """Слот: задача создана"""
        self._job_output_dirs[job_info.id] = self._pending_output_dir
        self._save_job_mappings()
        
        from app.gui.toast import show_toast
        show_toast(self, f"Задача создана: {job_info.id[:8]}...", duration=2500)
        self._refresh_jobs(manual=True)
    
    def _on_job_create_error(self, error_type: str, message: str):
        """Слот: ошибка создания задачи"""
        titles = {"auth": "Ошибка авторизации", "size": "Файл слишком большой", "server": "Ошибка сервера", "generic": "Ошибка"}
        QMessageBox.critical(self, titles.get(error_type, "Ошибка"), message)
    
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
        """Добавить промпты к IMAGE блокам"""
        from rd_core.models import BlockType
        
        if not hasattr(self.main_window, 'prompt_manager'):
            return
        
        pm = self.main_window.prompt_manager
        
        for block in blocks:
            if block.block_type == BlockType.IMAGE:
                if getattr(block, "prompt", None):
                    continue
                prompt = pm.load_prompt("image")
                if prompt:
                    block.prompt = prompt

    def _on_download_started(self, job_id: str, total_files: int):
        """Слот: начало скачивания"""
        self._download_dialog = QProgressDialog(f"Скачивание файлов задачи {job_id[:8]}...", None, 0, total_files, self)
        self._download_dialog.setWindowTitle("Загрузка результатов")
        self._download_dialog.setWindowModality(Qt.WindowModal)
        self._download_dialog.setMinimumDuration(0)
        self._download_dialog.setValue(0)
        self._download_dialog.show()

    def _on_download_progress(self, job_id: str, current: int, filename: str):
        """Слот: прогресс скачивания"""
        if self._download_dialog:
            self._download_dialog.setValue(current)
            self._download_dialog.setLabelText(f"Скачивание: {filename}")

    def _on_download_finished(self, job_id: str, extract_dir: str):
        """Слот: скачивание завершено"""
        if self._download_dialog:
            self._download_dialog.close()
            self._download_dialog = None
        
        from app.gui.toast import show_toast
        show_toast(self.main_window, f"Результат скачан: {job_id[:8]}...")
        
        if self._pending_open_in_editor == job_id:
            self._pending_open_in_editor = None
            self._open_job_in_editor_internal(job_id)

    def _on_download_error(self, job_id: str, error_msg: str):
        """Слот: ошибка скачивания"""
        if self._download_dialog:
            self._download_dialog.close()
            self._download_dialog = None
        
        self._pending_open_in_editor = None
        QMessageBox.critical(self, "Ошибка загрузки", f"Не удалось скачать файлы:\n{error_msg}")
    
    def _on_rerun_created(self, old_job_id: str, new_job_info):
        """Слот: повторное распознавание создано"""
        from app.gui.toast import show_toast
        if new_job_info:
            show_toast(self, f"Задача пересоздана: {new_job_info.id[:8]}...", duration=2500)
        else:
            show_toast(self, f"Задача перезапущена: {old_job_id[:8]}...", duration=2500)
        self._refresh_jobs(manual=True)
    
    def _on_rerun_error(self, job_id: str, error_msg: str):
        """Слот: ошибка повторного распознавания"""
        QMessageBox.critical(self, "Ошибка", f"Не удалось повторить распознавание:\n{error_msg}")
    
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
    
    def _format_datetime_utc3(self, dt_str: str) -> str:
        """Конвертировать UTC время в UTC+3 (МСК)"""
        from app.gui.utils import format_datetime_utc3
        return format_datetime_utc3(dt_str)
