"""Панель для управления Remote OCR задачами"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class RemoteOCRPanel(DownloadMixin, QDockWidget):
    """Dock-панель для Remote OCR задач"""
    
    # Интервалы опроса (мс)
    POLL_INTERVAL_PROCESSING = 5000   # при активных задачах
    POLL_INTERVAL_IDLE = 30000        # в покое
    POLL_INTERVAL_ERROR = 60000       # при ошибках (backoff)
    
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
        self._is_fetching = False  # Флаг: запрос уже выполняется
        self._is_manual_refresh = False  # Флаг: ручное обновление
        
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
        self._signals.draft_created.connect(self._on_draft_created)
        self._signals.draft_create_error.connect(self._on_draft_create_error)
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
        # Защита от множественных одновременных запросов
        if self._is_fetching:
            return
        self._is_fetching = True
        self._is_manual_refresh = manual
        
        # Показываем "Загрузка" только при ручном обновлении
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
        
        # Адаптивный интервал опроса
        self._has_active_jobs = any(j.status in ("queued", "processing") for j in jobs)
        new_interval = self.POLL_INTERVAL_PROCESSING if self._has_active_jobs else self.POLL_INTERVAL_IDLE
        if self.refresh_timer.interval() != new_interval:
            self.refresh_timer.setInterval(new_interval)
    
    def _on_jobs_error(self, error_msg: str):
        """Слот: ошибка загрузки списка"""
        self._is_fetching = False
        self.status_label.setText("🔴 Сервер недоступен")
        self._consecutive_errors += 1
        # Exponential backoff при ошибках
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
            
            # Кнопка Пауза/Возобновить
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
            self.jobs_table.setCellWidget(row, 5, actions_widget)
        
        self.jobs_table.setSortingEnabled(True)

    def _open_job_in_editor(self, job_id: str):
        """Открыть результат задачи в редакторе"""
        # Проверяем, не открыт ли уже этот job
        for project in self.main_window.project_manager.projects.values():
            if project.remote_job_id == job_id:
                QMessageBox.information(self, "Задание открыто", 
                    f"Это задание уже открыто в проекте «{project.name}»")
                self.main_window.project_manager.set_active_project(project.id)
                return
        
        if job_id in self._job_output_dirs:
            extract_dir = Path(self._job_output_dirs[job_id])
        else:
            from app.gui.folder_settings_dialog import get_download_jobs_dir
            download_dir = get_download_jobs_dir()
            if download_dir and Path(download_dir).exists():
                extract_dir = Path(download_dir) / f"result_{job_id[:8]}"
            else:
                import tempfile
                tmp_base = Path(tempfile.gettempdir()) / "rd_ocr_results"
                tmp_base.mkdir(exist_ok=True)
                extract_dir = tmp_base / f"result_{job_id[:8]}"
            self._job_output_dirs[job_id] = str(extract_dir)
            self._save_job_mappings()

        annotation_path = extract_dir / "annotation.json"
        pdf_path = extract_dir / "document.pdf"

        if not annotation_path.exists() or not pdf_path.exists():
            self._auto_download_result(job_id, open_after=True)
            return
        
        self._open_job_in_editor_internal(job_id)

    def _open_job_in_editor_internal(self, job_id: str):
        """Внутренний метод открытия задачи"""
        try:
            self.main_window._save_current_annotation_to_cache()
            
            if hasattr(self.main_window, 'navigation_manager') and self.main_window.navigation_manager:
                self.main_window.navigation_manager.save_current_zoom()
            
            extract_dir = Path(self._job_output_dirs[job_id])
            annotation_path = extract_dir / "annotation.json"
            pdf_path = extract_dir / "document.pdf"

            if not annotation_path.exists():
                QMessageBox.warning(self, "Нет результата", "annotation.json не найден")
                return

            from rd_core.annotation_io import AnnotationIO
            loaded_doc = AnnotationIO.load_annotation(str(annotation_path))
            if not loaded_doc:
                QMessageBox.critical(self, "Ошибка", "Не удалось загрузить annotation.json")
                return

            if pdf_path.exists():
                loaded_doc.pdf_path = str(pdf_path)
            else:
                try:
                    pdf_path_obj = Path(loaded_doc.pdf_path)
                    if not pdf_path_obj.is_absolute():
                        loaded_doc.pdf_path = str((annotation_path.parent / pdf_path_obj).resolve())
                except Exception:
                    pass

            pdf_abs_path = Path(loaded_doc.pdf_path)
            if not pdf_abs_path.exists():
                QMessageBox.warning(self, "PDF не найден", f"PDF файл не найден:\n{loaded_doc.pdf_path}")
                return

            task_name = None
            try:
                client = self._get_client()
                if client:
                    job_details = client.get_job_details(job_id)
                    task_name = job_details.get("task_name") or job_details.get("document_name", "")
            except Exception:
                pass
            
            if not task_name:
                task_name = pdf_abs_path.stem
            
            project_id = self.main_window.project_manager.create_project(task_name)
            project = self.main_window.project_manager.get_project(project_id)
            if project:
                project.remote_job_id = job_id
            self.main_window.project_manager.add_file_to_project(project_id, str(pdf_abs_path), str(annotation_path))
            self.main_window.project_manager.set_active_project(project_id)
            self.main_window.project_manager.set_active_file_in_project(project_id, 0)
            
            self.main_window._current_project_id = project_id
            self.main_window._current_file_index = 0

            try:
                from rd_core.models import Page
                from rd_core.pdf_utils import PDFDocument

                blocks_by_page: dict[int, list] = {}
                page_dims: dict[int, tuple[int, int]] = {}

                for p in loaded_doc.pages:
                    if getattr(p, "width", 0) and getattr(p, "height", 0):
                        page_dims[p.page_number] = (int(p.width), int(p.height))
                    for b in (p.blocks or []):
                        blocks_by_page.setdefault(int(getattr(b, "page_index", p.page_number)), []).append(b)

                with PDFDocument(str(pdf_abs_path)) as pdf:
                    new_pages = []
                    for page_idx in range(pdf.page_count):
                        dims = page_dims.get(page_idx) or pdf.get_page_dimensions(page_idx) or (595, 842)
                        blocks = blocks_by_page.get(page_idx, [])
                        try:
                            blocks.sort(key=lambda bl: bl.coords_px[1])
                        except Exception:
                            pass
                        new_pages.append(Page(page_number=page_idx, width=int(dims[0]), height=int(dims[1]), blocks=blocks))
                loaded_doc.pages = new_pages
            except Exception:
                pass

            try:
                crops_dir = annotation_path.parent / "crops"
                if crops_dir.exists():
                    for page in loaded_doc.pages:
                        for block in page.blocks:
                            if not getattr(block, "image_file", None):
                                continue
                            fname = Path(block.image_file).name
                            local_img = crops_dir / fname
                            block.image_file = str(local_img.resolve()) if local_img.exists() else str(local_img)
            except Exception:
                pass

            self.main_window.annotation_document = loaded_doc

            if hasattr(self.main_window, "page_viewer") and self.main_window.page_viewer:
                try:
                    self.main_window.page_viewer.selected_block_idx = None
                    self.main_window.page_viewer.selected_block_indices = []
                except Exception:
                    pass

            self.main_window._load_cleaned_pdf(loaded_doc.pdf_path, keep_annotation=True)

            if getattr(self.main_window, "blocks_tree_manager", None):
                self.main_window.blocks_tree_manager.update_blocks_tree()

        except Exception as e:
            logger.error(f"Ошибка открытия задачи {job_id}: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть задачу:\n{e}")
    
    def _create_job(self):
        """Создать новую задачу OCR"""
        if not self.main_window.pdf_document or not self.main_window.annotation_document:
            QMessageBox.warning(self, "Ошибка", "Откройте PDF документ")
            return
        
        pdf_path = self.main_window.annotation_document.pdf_path
        # Fallback: использовать путь из активного файла проекта
        if not pdf_path or not Path(pdf_path).exists():
            active_project = self.main_window.project_manager.get_active_project()
            if active_project:
                active_file = active_project.get_active_file()
                if active_file and Path(active_file.pdf_path).exists():
                    pdf_path = active_file.pdf_path
                    self.main_window.annotation_document.pdf_path = pdf_path
        
        if not pdf_path or not Path(pdf_path).exists():
            QMessageBox.warning(self, "Ошибка", "PDF файл не найден")
            return
        
        from PySide6.QtWidgets import QDialog
        from app.gui.ocr_dialog import OCRDialog
        
        task_name = ""
        active_project = self.main_window.project_manager.get_active_project()
        if active_project:
            task_name = active_project.name
        
        dialog = OCRDialog(self.main_window, task_name=task_name)
        if dialog.exec() != QDialog.Accepted:
            return
        
        self._last_output_dir = dialog.output_dir
        self._last_engine = dialog.ocr_backend
        
        selected_blocks = self._get_selected_blocks()
        if not selected_blocks:
            QMessageBox.warning(self, "Ошибка", "Нет блоков для распознавания")
            return
        
        client = self._get_client()
        if client is None:
            QMessageBox.warning(self, "Ошибка", "Клиент не инициализирован")
            return
        
        engine = "openrouter"
        if dialog.ocr_backend == "datalab":
            engine = "datalab"
        elif dialog.ocr_backend == "openrouter":
            engine = "openrouter"
        
        self._pending_output_dir = dialog.output_dir
        task_name = self.main_window.project_manager.get_active_project().name if self.main_window.project_manager.get_active_project() else ""
        
        from app.gui.toast import show_toast
        show_toast(self, "Отправка задачи...", duration=1500)
        
        self._executor.submit(
            self._create_job_bg, client, pdf_path, selected_blocks, task_name, engine,
            getattr(dialog, "text_model", None),
            getattr(dialog, "table_model", None),
            getattr(dialog, "image_model", None),
        )
        logger.info(f"OCR задача: image_model={getattr(dialog, 'image_model', None)}")
    
    def _create_job_bg(self, client, pdf_path, blocks, task_name, engine, text_model, table_model, image_model):
        """Фоновое создание задачи"""
        try:
            from app.remote_ocr_client import AuthenticationError, PayloadTooLargeError, ServerError
            
            job_info = client.create_job(pdf_path, blocks, task_name=task_name, engine=engine,
                                        text_model=text_model, table_model=table_model, image_model=image_model)
            self._signals.job_created.emit(job_info)
        except AuthenticationError:
            self._signals.job_create_error.emit("auth", "Неверный API ключ.")
        except PayloadTooLargeError:
            self._signals.job_create_error.emit("size", "PDF файл превышает лимит сервера.")
        except ServerError as e:
            self._signals.job_create_error.emit("server", f"Сервер недоступен.\n{e}")
        except Exception as e:
            self._signals.job_create_error.emit("generic", str(e))
    
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
    
    def _save_draft(self):
        """Сохранить черновик на сервере"""
        if not self.main_window.pdf_document or not self.main_window.annotation_document:
            QMessageBox.warning(self, "Ошибка", "Откройте PDF документ")
            return
        
        pdf_path = self.main_window.annotation_document.pdf_path
        # Fallback: использовать путь из активного файла проекта
        if not pdf_path or not Path(pdf_path).exists():
            active_project = self.main_window.project_manager.get_active_project()
            if active_project:
                active_file = active_project.get_active_file()
                if active_file and Path(active_file.pdf_path).exists():
                    pdf_path = active_file.pdf_path
                    self.main_window.annotation_document.pdf_path = pdf_path
        
        if not pdf_path or not Path(pdf_path).exists():
            QMessageBox.warning(self, "Ошибка", "PDF файл не найден")
            return
        
        total_blocks = sum(len(p.blocks) for p in self.main_window.annotation_document.pages)
        if total_blocks == 0:
            QMessageBox.warning(self, "Ошибка", "Нет блоков для сохранения")
            return
        
        client = self._get_client()
        if client is None:
            QMessageBox.warning(self, "Ошибка", "Клиент не инициализирован")
            return
        
        task_name = ""
        active_project = self.main_window.project_manager.get_active_project()
        if active_project:
            task_name = active_project.name
        
        from app.gui.folder_settings_dialog import get_new_jobs_dir
        from app.gui.ocr_dialog import transliterate_to_latin
        
        base_dir = get_new_jobs_dir()
        if base_dir:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_task_name = transliterate_to_latin(task_name) if task_name else "draft"
            unique_name = f"{safe_task_name}_{timestamp}"
            self._pending_output_dir = str(Path(base_dir) / unique_name)
        else:
            import tempfile
            self._pending_output_dir = str(Path(tempfile.gettempdir()) / "rd_draft")
        
        from app.gui.toast import show_toast
        show_toast(self, "Сохранение черновика...", duration=1500)
        
        self._executor.submit(self._save_draft_bg, client, pdf_path, self.main_window.annotation_document, task_name)
    
    def _save_draft_bg(self, client, pdf_path, annotation_document, task_name):
        """Фоновое сохранение черновика"""
        try:
            from app.remote_ocr_client import AuthenticationError, PayloadTooLargeError, ServerError
            
            job_info = client.create_draft(pdf_path, annotation_document, task_name=task_name)
            self._signals.draft_created.emit(job_info)
        except AuthenticationError:
            self._signals.draft_create_error.emit("auth", "Неверный API ключ.")
        except PayloadTooLargeError:
            self._signals.draft_create_error.emit("size", "PDF файл превышает лимит сервера.")
        except ServerError as e:
            self._signals.draft_create_error.emit("server", f"Сервер недоступен.\n{e}")
        except Exception as e:
            self._signals.draft_create_error.emit("generic", str(e))
    
    def _on_draft_created(self, job_info):
        """Слот: черновик создан"""
        self._job_output_dirs[job_info.id] = self._pending_output_dir
        self._save_job_mappings()
        
        try:
            output_dir = Path(self._pending_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            import shutil
            pdf_path = self.main_window.annotation_document.pdf_path
            shutil.copy2(pdf_path, output_dir / "document.pdf")
            
            from rd_core.annotation_io import AnnotationIO
            AnnotationIO.save_annotation(self.main_window.annotation_document, str(output_dir / "annotation.json"))
        except Exception as e:
            logger.warning(f"Ошибка локального сохранения черновика: {e}")
        
        from app.gui.toast import show_toast
        show_toast(self, f"Черновик сохранён: {job_info.id[:8]}...", duration=2500)
        self._refresh_jobs(manual=True)
    
    def _on_draft_create_error(self, error_type: str, message: str):
        """Слот: ошибка создания черновика"""
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
    
    def _show_job_details(self, job_id: str):
        """Показать детальную информацию о задаче"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            job_details = client.get_job_details(job_id)
            
            if job_id not in self._job_output_dirs:
                from app.gui.folder_settings_dialog import get_download_jobs_dir
                download_dir = get_download_jobs_dir()
                if download_dir and Path(download_dir).exists():
                    extract_dir = Path(download_dir) / f"result_{job_id[:8]}"
                else:
                    import tempfile
                    extract_dir = Path(tempfile.gettempdir()) / "rd_ocr_results" / f"result_{job_id[:8]}"
                
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()
            
            extract_dir = Path(self._job_output_dirs[job_id])
            if job_details.get("status") == "done" and not (extract_dir / "annotation.json").exists():
                self._auto_download_result(job_id)
            
            job_details["client_output_dir"] = self._job_output_dirs[job_id]
            
            from app.gui.job_details_dialog import JobDetailsDialog
            dialog = JobDetailsDialog(job_details, self)
            dialog.exec()
        except Exception as e:
            logger.error(f"Ошибка получения информации о задаче: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить информацию:\n{e}")
    
    def _delete_job(self, job_id: str):
        """Удалить задачу и все связанные файлы (R2, Supabase, локальная папка)"""
        reply = QMessageBox.question(self, "Подтверждение удаления",
            f"Удалить задачу {job_id[:8]}...?\n\nБудут удалены:\n• Запись на сервере\n• Файлы в R2\n• Локальная папка",
            QMessageBox.Yes | QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return
        
        client = self._get_client()
        if client is None:
            return
        
        try:
            # Удаляем на сервере (R2 + Supabase удаляются там)
            client.delete_job(job_id)
            
            # Удаляем локальную папку
            if job_id in self._job_output_dirs:
                local_dir = Path(self._job_output_dirs[job_id])
                if local_dir.exists():
                    import shutil
                    try:
                        shutil.rmtree(local_dir)
                    except Exception as e:
                        logger.warning(f"Ошибка удаления локальной папки: {e}")
                
                del self._job_output_dirs[job_id]
                self._save_job_mappings()
            
            from app.gui.toast import show_toast
            show_toast(self, "Задача удалена")
            self._refresh_jobs(manual=True)
            
        except Exception as e:
            logger.error(f"Ошибка удаления задачи: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить задачу:\n{e}")
    
    def _pause_job(self, job_id: str):
        """Поставить задачу на паузу"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            if client.pause_job(job_id):
                from app.gui.toast import show_toast
                show_toast(self, f"Задача {job_id[:8]}... на паузе")
                self._refresh_jobs(manual=True)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось поставить на паузу")
        except Exception as e:
            logger.error(f"Ошибка паузы задачи: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось поставить на паузу:\n{e}")
    
    def _resume_job(self, job_id: str):
        """Возобновить задачу с паузы"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            if client.resume_job(job_id):
                from app.gui.toast import show_toast
                show_toast(self, f"Задача {job_id[:8]}... возобновлена")
                self._refresh_jobs(manual=True)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось возобновить")
        except Exception as e:
            logger.error(f"Ошибка возобновления задачи: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось возобновить:\n{e}")
    
    def _rerun_job(self, job_id: str):
        """Повторное распознавание с сохранёнными настройками"""
        reply = QMessageBox.question(
            self, "Повторное распознавание",
            f"Повторить распознавание задачи {job_id[:8]}?\n\nВсе результаты будут удалены и созданы заново.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        
        from app.gui.toast import show_toast
        show_toast(self, "Подготовка повторного распознавания...", duration=1500)
        
        self._executor.submit(self._rerun_job_bg, job_id)
    
    def _rerun_job_bg(self, job_id: str):
        """Фоновая повторная отправка на распознавание"""
        try:
            client = self._get_client()
            if client is None:
                self._signals.rerun_error.emit(job_id, "Клиент не инициализирован")
                return
            
            # Получаем детали задачи
            job_details = client.get_job_details(job_id)
            r2_prefix = job_details.get("r2_prefix")
            
            # Удаляем локальные файлы результатов (но сохраняем PDF)
            if job_id in self._job_output_dirs:
                local_dir = Path(self._job_output_dirs[job_id])
                if local_dir.exists():
                    import shutil
                    for fname in ["annotation.json", "result.md"]:
                        fpath = local_dir / fname
                        if fpath.exists():
                            try:
                                fpath.unlink()
                            except Exception:
                                pass
                    crops_dir = local_dir / "crops"
                    if crops_dir.exists():
                        try:
                            shutil.rmtree(crops_dir)
                        except Exception:
                            pass
            
            # Удаляем файлы из R2
            if r2_prefix:
                try:
                    from rd_core.r2_storage import R2Storage
                    r2 = R2Storage()
                    r2_prefix_normalized = r2_prefix if r2_prefix.endswith('/') else f"{r2_prefix}/"
                    files_to_delete = []
                    paginator = r2.s3_client.get_paginator('list_objects_v2')
                    for page in paginator.paginate(Bucket=r2.bucket_name, Prefix=r2_prefix_normalized):
                        if 'Contents' in page:
                            for obj in page['Contents']:
                                key = obj['Key']
                                if key.startswith(r2_prefix_normalized):
                                    files_to_delete.append({'Key': key})
                    if files_to_delete:
                        for i in range(0, len(files_to_delete), 1000):
                            batch = files_to_delete[i:i+1000]
                            r2.s3_client.delete_objects(Bucket=r2.bucket_name, Delete={'Objects': batch})
                except Exception:
                    pass
            
            # Перезапускаем задачу на сервере (статус -> queued)
            from app.remote_ocr_client import AuthenticationError, ServerError
            
            if not client.restart_job(job_id):
                self._signals.rerun_error.emit(job_id, "Не удалось перезапустить задачу")
                return
            
            self._signals.rerun_created.emit(job_id, None)
            
        except AuthenticationError:
            self._signals.rerun_error.emit(job_id, "Неверный API ключ")
        except ServerError as e:
            self._signals.rerun_error.emit(job_id, f"Сервер недоступен: {e}")
        except Exception as e:
            logger.error(f"Ошибка повторного распознавания: {e}")
            self._signals.rerun_error.emit(job_id, str(e))
    
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
