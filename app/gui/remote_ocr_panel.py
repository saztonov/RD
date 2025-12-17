"""Панель для управления Remote OCR задачами"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QDockWidget, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFileDialog, QLabel, QProgressBar, QProgressDialog
)


class _WorkerSignals(QObject):
    """Сигналы для фоновых задач"""
    jobs_loaded = Signal(list)
    jobs_error = Signal(str)
    job_created = Signal(object)
    job_create_error = Signal(str, str)  # error_type, message
    # Сигналы для скачивания
    download_started = Signal(str, int)  # job_id, total_files
    download_progress = Signal(str, int, str)  # job_id, current_file_num, filename
    download_finished = Signal(str, str)  # job_id, extract_dir
    download_error = Signal(str, str)  # job_id, error_message
    # Сигналы для черновика
    draft_created = Signal(object)  # job_info
    draft_create_error = Signal(str, str)  # error_type, message

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class RemoteOCRPanel(QDockWidget):
    """Dock-панель для Remote OCR задач"""
    
    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__("Remote OCR Jobs", parent)
        self.setObjectName("RemoteOCRPanel")
        self.main_window = main_window
        self._client = None
        self._current_document_id = None
        self._last_output_dir = None
        self._last_engine = None
        self._job_output_dirs = {}  # Маппинг job_id -> output_dir
        self._config_file = Path.home() / ".rd" / "remote_ocr_jobs.json"
        
        # ThreadPool для фоновых операций
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._signals = _WorkerSignals()
        self._signals.jobs_loaded.connect(self._on_jobs_loaded)
        self._signals.jobs_error.connect(self._on_jobs_error)
        self._signals.job_created.connect(self._on_job_created)
        self._signals.job_create_error.connect(self._on_job_create_error)
        # Сигналы скачивания
        self._signals.download_started.connect(self._on_download_started)
        self._signals.download_progress.connect(self._on_download_progress)
        self._signals.download_finished.connect(self._on_download_finished)
        self._signals.download_error.connect(self._on_download_error)
        # Сигналы черновика
        self._signals.draft_created.connect(self._on_draft_created)
        self._signals.draft_create_error.connect(self._on_draft_create_error)
        
        self._download_dialog: Optional[QProgressDialog] = None
        self._pending_open_in_editor: Optional[str] = None  # job_id для открытия после скачивания
        
        self._load_job_mappings()
        self._setup_ui()
        self._setup_timer()
    
    def _setup_ui(self):
        """Настроить UI панели"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Заголовок и статус сервера
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Задачи:"))
        
        self.status_label = QLabel("🔴 Не подключено")
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setMaximumWidth(30)
        self.refresh_btn.setToolTip("Обновить список")
        self.refresh_btn.clicked.connect(self._refresh_jobs)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Таблица задач
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
        
        # Включаем сортировку
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
        # Таймер не запускается автоматически, только когда панель видима
    
    def _load_job_mappings(self):
        """Загрузить сохранённые маппинги job_id -> output_dir"""
        try:
            if self._config_file.exists():
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    self._job_output_dirs = json.load(f)
                logger.info(f"Загружено {len(self._job_output_dirs)} маппингов задач")
        except Exception as e:
            logger.warning(f"Ошибка загрузки маппингов задач: {e}")
            self._job_output_dirs = {}
    
    def _save_job_mappings(self):
        """Сохранить маппинги job_id -> output_dir"""
        try:
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._job_output_dirs, f, ensure_ascii=False, indent=2)
            logger.debug(f"Сохранено {len(self._job_output_dirs)} маппингов задач")
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
    
    def _check_server(self) -> bool:
        """Проверить доступность сервера"""
        client = self._get_client()
        if client is None:
            self.status_label.setText("🔴 Ошибка клиента")
            return False
        
        try:
            if client.health():
                self.status_label.setText("🟢 Подключено")
                return True
        except Exception:
            pass
        
        self.status_label.setText("🔴 Сервер недоступен")
        return False
    
    def _refresh_jobs(self):
        """Обновить список задач (в фоне)"""
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
        self._update_table(jobs)
        self.status_label.setText("🟢 Подключено")
    
    def _on_jobs_error(self, error_msg: str):
        """Слот: ошибка загрузки списка"""
        self.status_label.setText("🔴 Сервер недоступен")
    
    def _update_table(self, jobs):
        """Обновить таблицу задач"""
        # Отключаем сортировку на время обновления
        self.jobs_table.setSortingEnabled(False)
        self.jobs_table.setRowCount(0)
        
        # Автоскачивание для завершённых задач
        for job in jobs:
            if job.status == "done" and job.id in self._job_output_dirs:
                extract_dir = Path(self._job_output_dirs[job.id])
                if not (extract_dir / "annotation.json").exists():
                    self._auto_download_result(job.id)
        
        for idx, job in enumerate(jobs, start=1):
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)
            
            # Нумерация
            num_item = QTableWidgetItem(str(idx))
            num_item.setData(Qt.UserRole, job.id)  # Сохраняем ID для операций
            self.jobs_table.setItem(row, 0, num_item)
            
            # Наименование задания (используем task_name если есть, иначе document_name)
            display_name = job.task_name if job.task_name else job.document_name
            self.jobs_table.setItem(row, 1, QTableWidgetItem(display_name))
            
            # Время начала в формате 20:02 25.01.2025
            created_at_str = self._format_datetime_utc3(job.created_at)
            created_item = QTableWidgetItem(created_at_str)
            created_item.setData(Qt.UserRole, job.created_at)  # Сохраняем исходное время для сортировки
            self.jobs_table.setItem(row, 2, created_item)
            
            # Статус
            status_text = {
                "draft": "📝 Черновик",
                "queued": "⏳ В очереди",
                "processing": "🔄 Обработка",
                "done": "✅ Готово",
                "error": "❌ Ошибка"
            }.get(job.status, job.status)
            
            status_item = QTableWidgetItem(status_text)
            if job.error_message:
                status_item.setToolTip(job.error_message)
            self.jobs_table.setItem(row, 3, status_item)
            
            # Прогресс
            progress_text = f"{int(job.progress * 100)}%"
            progress_item = QTableWidgetItem(progress_text)
            progress_item.setData(Qt.UserRole, job.progress)  # Для корректной сортировки
            self.jobs_table.setItem(row, 4, progress_item)
            
            # Кнопки действий
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)
            
            # Кнопка открыть в редакторе
            open_btn = QPushButton("✏️")
            open_btn.setToolTip("Открыть в редакторе")
            open_btn.setMaximumWidth(40)
            open_btn.clicked.connect(lambda checked, jid=job.id: self._open_job_in_editor(jid))
            actions_layout.addWidget(open_btn)
            
            # Кнопка информации (для всех статусов)
            info_btn = QPushButton("ℹ️")
            info_btn.setToolTip("Информация о задаче")
            info_btn.setMaximumWidth(40)
            info_btn.clicked.connect(lambda checked, jid=job.id: self._show_job_details(jid))
            actions_layout.addWidget(info_btn)
            
            # Кнопка удалить (для всех статусов)
            delete_btn = QPushButton("🗑️")
            delete_btn.setToolTip("Удалить задачу и все файлы")
            delete_btn.setMaximumWidth(40)
            delete_btn.clicked.connect(lambda checked, jid=job.id: self._delete_job(jid))
            actions_layout.addWidget(delete_btn)
            
            actions_layout.addStretch()
            self.jobs_table.setCellWidget(row, 5, actions_widget)
        
        # Включаем сортировку обратно
        self.jobs_table.setSortingEnabled(True)

    def _open_job_in_editor(self, job_id: str):
        """Открыть результат задачи (PDF + annotation.json) в редакторе"""
        # Определяем папку результата
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

        # Если результата нет локально — запускаем скачивание с прогрессом
        if not annotation_path.exists() or not pdf_path.exists():
            self._auto_download_result(job_id, open_after=True)
            return
        
        # Файлы есть - открываем сразу
        self._open_job_in_editor_internal(job_id)

    def _open_job_in_editor_internal(self, job_id: str):
        """Внутренний метод открытия задачи в редакторе (файлы уже скачаны)"""
        try:
            # Сохраняем текущую аннотацию в кеш перед переключением
            self.main_window._save_current_annotation_to_cache()
            
            # Сохраняем зум перед переключением
            if hasattr(self.main_window, 'navigation_manager') and self.main_window.navigation_manager:
                self.main_window.navigation_manager.save_current_zoom()
            
            extract_dir = Path(self._job_output_dirs[job_id])
            annotation_path = extract_dir / "annotation.json"
            pdf_path = extract_dir / "document.pdf"

            if not annotation_path.exists():
                QMessageBox.warning(self, "Нет результата", "annotation.json не найден (задача не готова или результат не скачан).")
                return

            from rd_core.annotation_io import AnnotationIO
            loaded_doc = AnnotationIO.load_annotation(str(annotation_path))
            if not loaded_doc:
                QMessageBox.critical(self, "Ошибка", "Не удалось загрузить annotation.json")
                return

            # Используем локальный document.pdf если есть
            if pdf_path.exists():
                loaded_doc.pdf_path = str(pdf_path)
            else:
                # Поддержка относительных путей внутри annotation.json
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

            # Получаем task_name из задачи для создания проекта
            task_name = None
            try:
                client = self._get_client()
                if client:
                    job_details = client.get_job_details(job_id)
                    task_name = job_details.get("task_name") or job_details.get("document_name", "")
            except Exception:
                pass
            
            if not task_name:
                task_name = pdf_abs_path.stem  # Используем имя файла без расширения
            
            # Создаём проект в боковом меню
            project_id = self.main_window.project_manager.create_project(task_name)
            self.main_window.project_manager.add_file_to_project(project_id, str(pdf_abs_path), str(annotation_path))
            self.main_window.project_manager.set_active_project(project_id)
            self.main_window.project_manager.set_active_file_in_project(project_id, 0)
            
            # Устанавливаем маркеры проекта/файла
            self.main_window._current_project_id = project_id
            self.main_window._current_file_index = 0

            # Нормализуем страницы: индекс списка == номер страницы (иначе GUI рисует блоки не на тех страницах)
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

            # Фиксим image_file (сервер сохраняет абсолютные пути)
            try:
                crops_dir = annotation_path.parent / "crops"
                if crops_dir.exists():
                    for page in loaded_doc.pages:
                        for block in page.blocks:
                            if not getattr(block, "image_file", None):
                                continue
                            fname = Path(block.image_file).name
                            local_img = (crops_dir / fname)
                            if local_img.exists():
                                block.image_file = str(local_img.resolve())
                            else:
                                block.image_file = str(local_img)
            except Exception:
                pass

            # Открываем в главном редакторе
            self.main_window.annotation_document = loaded_doc

            # Сбрасываем выделение блоков (иначе тянется с прошлого документа)
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
            logger.error(f"Ошибка открытия задачи {job_id} в редакторе: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть задачу:\n{e}")
    
    def _create_job(self):
        """Создать новую задачу OCR с настройками"""
        # Проверяем наличие PDF
        if not self.main_window.pdf_document or not self.main_window.annotation_document:
            QMessageBox.warning(self, "Ошибка", "Откройте PDF документ")
            return
        
        pdf_path = self.main_window.annotation_document.pdf_path
        if not pdf_path or not Path(pdf_path).exists():
            QMessageBox.warning(self, "Ошибка", "PDF файл не найден")
            return
        
        # Открываем диалог настройки OCR
        from PySide6.QtWidgets import QDialog
        from app.gui.ocr_dialog import OCRDialog
        
        task_name = ""
        active_project = self.main_window.project_manager.get_active_project()
        if active_project:
            task_name = active_project.name
        
        dialog = OCRDialog(self.main_window, task_name=task_name)
        if dialog.exec() != QDialog.Accepted:
            return
        
        # Сохраняем настройки для последующего использования
        self._last_output_dir = dialog.output_dir
        self._last_engine = dialog.ocr_backend
        
        # Собираем блоки после подтверждения настроек
        selected_blocks = self._get_selected_blocks()
        if not selected_blocks:
            QMessageBox.warning(self, "Ошибка", "Нет блоков для распознавания")
            return
        
        # Логируем распределение блоков по страницам
        pages_summary = {}
        for b in selected_blocks:
            pages_summary[b.page_index] = pages_summary.get(b.page_index, 0) + 1
        logger.info(f"Отправка на OCR: {len(selected_blocks)} блоков, страницы: {pages_summary}")
        
        client = self._get_client()
        if client is None:
            QMessageBox.warning(self, "Ошибка", "Клиент не инициализирован")
            return
        
        # Определяем engine для сервера
        engine = "openrouter"  # По умолчанию
        if dialog.ocr_backend == "datalab":
            engine = "datalab"
        elif dialog.ocr_backend == "openrouter":
            engine = "openrouter"
        
        # Сохраняем output_dir для использования после создания
        self._pending_output_dir = dialog.output_dir
        task_name = self.main_window.project_manager.get_active_project().name if self.main_window.project_manager.get_active_project() else ""
        
        from app.gui.toast import show_toast
        show_toast(self, "Отправка задачи...", duration=1500)
        
        # Запускаем создание в фоне
        self._executor.submit(
            self._create_job_bg,
            client,
            pdf_path,
            selected_blocks,
            task_name,
            engine,
            getattr(dialog, "text_model", None),
            getattr(dialog, "table_model", None),
            getattr(dialog, "image_model", None),
        )
    
    def _create_job_bg(self, client, pdf_path, blocks, task_name, engine, text_model, table_model, image_model):
        """Фоновое создание задачи"""
        try:
            from app.remote_ocr_client import AuthenticationError, PayloadTooLargeError, ServerError
            
            logger.info(f"[BG] Создание задачи: {len(blocks)} блоков, engine={engine}")
            job_info = client.create_job(
                pdf_path,
                blocks,
                task_name=task_name,
                engine=engine,
                text_model=text_model,
                table_model=table_model,
                image_model=image_model,
            )
            logger.info(f"[BG] Задача создана: {job_info.id}")
            self._signals.job_created.emit(job_info)
        except AuthenticationError:
            logger.error("[BG] Ошибка авторизации")
            self._signals.job_create_error.emit("auth", "Неверный API ключ.\n\nПроверьте REMOTE_OCR_API_KEY в .env файле.")
        except PayloadTooLargeError:
            logger.error("[BG] Файл слишком большой")
            self._signals.job_create_error.emit("size", "PDF файл превышает лимит сервера.\n\nМаксимум: 500 МБ")
        except ServerError as e:
            logger.error(f"[BG] Ошибка сервера: {e}")
            self._signals.job_create_error.emit("server", f"Сервер временно недоступен.\n\nПопробуйте позже.\n{e}")
        except Exception as e:
            logger.error(f"[BG] Ошибка создания задачи: {e}", exc_info=True)
            self._signals.job_create_error.emit("generic", str(e))
    
    def _on_job_created(self, job_info):
        """Слот: задача создана"""
        logger.info(f"[SLOT] job_created: {job_info.id}")
        self._job_output_dirs[job_info.id] = self._pending_output_dir
        self._save_job_mappings()
        
        from app.gui.toast import show_toast
        show_toast(self, f"Задача создана: {job_info.id[:8]}...", duration=2500)
        self._refresh_jobs()
    
    def _on_job_create_error(self, error_type: str, message: str):
        """Слот: ошибка создания задачи"""
        titles = {
            "auth": "Ошибка авторизации",
            "size": "Файл слишком большой",
            "server": "Ошибка сервера",
            "generic": "Ошибка"
        }
        QMessageBox.critical(self, titles.get(error_type, "Ошибка"), message)
    
    def _save_draft(self):
        """Сохранить черновик (PDF + разметка) на сервере"""
        # Проверяем наличие PDF
        if not self.main_window.pdf_document or not self.main_window.annotation_document:
            QMessageBox.warning(self, "Ошибка", "Откройте PDF документ")
            return
        
        pdf_path = self.main_window.annotation_document.pdf_path
        if not pdf_path or not Path(pdf_path).exists():
            QMessageBox.warning(self, "Ошибка", "PDF файл не найден")
            return
        
        # Проверяем наличие блоков
        total_blocks = sum(len(p.blocks) for p in self.main_window.annotation_document.pages)
        if total_blocks == 0:
            QMessageBox.warning(self, "Ошибка", "Нет блоков для сохранения")
            return
        
        client = self._get_client()
        if client is None:
            QMessageBox.warning(self, "Ошибка", "Клиент не инициализирован")
            return
        
        # Получаем имя задания
        task_name = ""
        active_project = self.main_window.project_manager.get_active_project()
        if active_project:
            task_name = active_project.name
        
        # Сохраняем output_dir для использования после создания
        from app.gui.folder_settings_dialog import get_new_jobs_dir
        from app.gui.ocr_dialog import transliterate_to_latin
        from datetime import datetime
        
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
        
        # Запускаем сохранение в фоне
        self._executor.submit(
            self._save_draft_bg,
            client,
            pdf_path,
            self.main_window.annotation_document,
            task_name
        )
    
    def _save_draft_bg(self, client, pdf_path, annotation_document, task_name):
        """Фоновое сохранение черновика"""
        try:
            from app.remote_ocr_client import AuthenticationError, PayloadTooLargeError, ServerError
            
            logger.info(f"[BG] Сохранение черновика: {task_name}")
            job_info = client.create_draft(
                pdf_path,
                annotation_document,
                task_name=task_name
            )
            logger.info(f"[BG] Черновик создан: {job_info.id}")
            self._signals.draft_created.emit(job_info)
        except AuthenticationError:
            logger.error("[BG] Ошибка авторизации при сохранении черновика")
            self._signals.draft_create_error.emit("auth", "Неверный API ключ.\n\nПроверьте REMOTE_OCR_API_KEY в .env файле.")
        except PayloadTooLargeError:
            logger.error("[BG] Файл слишком большой")
            self._signals.draft_create_error.emit("size", "PDF файл превышает лимит сервера.\n\nМаксимум: 500 МБ")
        except ServerError as e:
            logger.error(f"[BG] Ошибка сервера: {e}")
            self._signals.draft_create_error.emit("server", f"Сервер временно недоступен.\n\nПопробуйте позже.\n{e}")
        except Exception as e:
            logger.error(f"[BG] Ошибка сохранения черновика: {e}", exc_info=True)
            self._signals.draft_create_error.emit("generic", str(e))
    
    def _on_draft_created(self, job_info):
        """Слот: черновик создан"""
        logger.info(f"[SLOT] draft_created: {job_info.id}")
        self._job_output_dirs[job_info.id] = self._pending_output_dir
        self._save_job_mappings()
        
        # Сохраняем локально в output_dir
        try:
            output_dir = Path(self._pending_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Копируем PDF
            import shutil
            pdf_path = self.main_window.annotation_document.pdf_path
            shutil.copy2(pdf_path, output_dir / "document.pdf")
            
            # Сохраняем annotation.json
            from rd_core.annotation_io import AnnotationIO
            AnnotationIO.save_annotation(
                self.main_window.annotation_document,
                str(output_dir / "annotation.json")
            )
            logger.info(f"Черновик сохранён локально: {output_dir}")
        except Exception as e:
            logger.warning(f"Ошибка локального сохранения черновика: {e}")
        
        from app.gui.toast import show_toast
        show_toast(self, f"Черновик сохранён: {job_info.id[:8]}...", duration=2500)
        self._refresh_jobs()
    
    def _on_draft_create_error(self, error_type: str, message: str):
        """Слот: ошибка создания черновика"""
        titles = {
            "auth": "Ошибка авторизации",
            "size": "Файл слишком большой",
            "server": "Ошибка сервера",
            "generic": "Ошибка"
        }
        QMessageBox.critical(self, titles.get(error_type, "Ошибка"), message)
    
    def _get_selected_blocks(self):
        """Получить ВСЕ блоки со ВСЕХ страниц для OCR"""
        blocks = []
        
        if self.main_window.annotation_document:
            for page in self.main_window.annotation_document.pages:
                if page.blocks:
                    blocks.extend(page.blocks)
            logger.info(f"Собраны ВСЕ блоки со всех страниц: {len(blocks)} блоков")
        
        # Добавляем промпты к IMAGE блокам
        self._attach_prompts_to_blocks(blocks)
        
        return blocks
    
    def _attach_prompts_to_blocks(self, blocks):
        """Добавить промпты к блокам (особенно IMAGE) перед отправкой на сервер"""
        from rd_core.models import BlockType
        
        if not hasattr(self.main_window, 'prompt_manager'):
            return
        
        pm = self.main_window.prompt_manager
        
        for block in blocks:
            # Для IMAGE блоков загружаем промпт типа image
            if block.block_type == BlockType.IMAGE:
                if getattr(block, "prompt", None):
                    continue
                prompt = None
                prompt = pm.load_prompt("image")
                
                if prompt:
                    block.prompt = prompt
                    logger.debug(f"Промпт для IMAGE блока {block.id}: image")
    
    def _auto_download_result(self, job_id: str, open_after: bool = False):
        """Запустить скачивание результата из R2 в фоне с прогрессом"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            job_details = client.get_job_details(job_id)
            r2_prefix = job_details.get("r2_prefix")
            
            if not r2_prefix:
                logger.warning(f"Задача {job_id} не имеет r2_prefix, пропускаем автоскачивание")
                return
            
            # Определяем папку для сохранения
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
            
            if job_id not in self._job_output_dirs:
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()
            
            # Проверяем, был ли уже скачан
            result_exists = extract_dir.exists() and (extract_dir / "annotation.json").exists()
            
            if not result_exists:
                if open_after:
                    self._pending_open_in_editor = job_id
                # Запускаем скачивание в фоне
                self._executor.submit(self._download_result_bg, job_id, r2_prefix, str(extract_dir))
            else:
                logger.debug(f"Результат уже скачан: {extract_dir}")
                if open_after:
                    self._open_job_in_editor_internal(job_id)
                
        except Exception as e:
            logger.error(f"Ошибка подготовки скачивания {job_id}: {e}")

    def _download_result_bg(self, job_id: str, r2_prefix: str, extract_dir: str):
        """Фоновое скачивание результата с прогрессом"""
        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
            
            extract_path = Path(extract_dir)
            extract_path.mkdir(parents=True, exist_ok=True)
            
            # Собираем список всех файлов для скачивания
            main_files = ["annotation.json", "result.md", "document.pdf"]
            crops_prefix = f"{r2_prefix}/crops/"
            crop_files = r2.list_by_prefix(crops_prefix)
            
            total_files = len(main_files) + len(crop_files)
            self._signals.download_started.emit(job_id, total_files)
            
            current = 0
            
            # Скачиваем основные файлы
            for filename in main_files:
                current += 1
                self._signals.download_progress.emit(job_id, current, filename)
                remote_key = f"{r2_prefix}/{filename}"
                local_path = extract_path / filename
                r2.download_file(remote_key, str(local_path))
            
            # Скачиваем кропы
            if crop_files:
                crops_dir = extract_path / "crops"
                crops_dir.mkdir(exist_ok=True)
                
                for remote_key in crop_files:
                    current += 1
                    filename = remote_key.split("/")[-1]
                    if filename:
                        self._signals.download_progress.emit(job_id, current, f"crops/{filename}")
                        local_path = crops_dir / filename
                        r2.download_file(remote_key, str(local_path))
            
            logger.info(f"✅ Результат скачан из R2: {extract_dir}")
            self._signals.download_finished.emit(job_id, extract_dir)
            
        except Exception as e:
            logger.error(f"Ошибка скачивания результата {job_id}: {e}")
            self._signals.download_error.emit(job_id, str(e))

    def _on_download_started(self, job_id: str, total_files: int):
        """Слот: начало скачивания - показываем диалог прогресса"""
        self._download_dialog = QProgressDialog(
            f"Скачивание файлов задачи {job_id[:8]}...",
            None,  # Без кнопки отмены
            0,
            total_files,
            self
        )
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
        
        # Если ожидалось открытие в редакторе - открываем
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
            
            # Определяем локальный путь
            if job_id not in self._job_output_dirs:
                from app.gui.folder_settings_dialog import get_download_jobs_dir
                download_dir = get_download_jobs_dir()
                if download_dir and Path(download_dir).exists():
                    extract_dir = Path(download_dir) / f"result_{job_id[:8]}"
                else:
                    import tempfile
                    tmp_base = Path(tempfile.gettempdir()) / "rd_ocr_results"
                    extract_dir = tmp_base / f"result_{job_id[:8]}"
                
                # Сохраняем маппинг
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()
            
            # Автоскачивание если задача готова но файлов нет
            extract_dir = Path(self._job_output_dirs[job_id])
            if job_details.get("status") == "done" and not (extract_dir / "annotation.json").exists():
                self._auto_download_result(job_id)
            
            # Добавляем локальный путь из маппинга
            job_details["client_output_dir"] = self._job_output_dirs[job_id]
            
            from app.gui.job_details_dialog import JobDetailsDialog
            dialog = JobDetailsDialog(job_details, self)
            dialog.exec()
        except Exception as e:
            logger.error(f"Ошибка получения информации о задаче: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить информацию:\n{e}")
    
    def _delete_job(self, job_id: str):
        """Удалить задачу и все связанные файлы (локальные + R2)"""
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить задачу {job_id[:8]}...?\n\nБудут удалены:\n• Запись на сервере\n• Локальная папка с результатами\n• Файлы в R2 Storage",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        client = self._get_client()
        if client is None:
            return
        
        try:
            # Получаем детали задачи для r2_prefix
            job_details = client.get_job_details(job_id)
            r2_prefix = job_details.get("r2_prefix")
            
            # 1. Удаляем локальную папку с результатами
            if job_id in self._job_output_dirs:
                local_dir = Path(self._job_output_dirs[job_id])
                if local_dir.exists():
                    import shutil
                    try:
                        shutil.rmtree(local_dir)
                        logger.info(f"✅ Удалена локальная папка: {local_dir}")
                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка удаления локальной папки {local_dir}: {e}")
                
                # Удаляем маппинг
                del self._job_output_dirs[job_id]
                self._save_job_mappings()
            
            # 2. Удаляем файлы из R2
            if r2_prefix:
                try:
                    from rd_core.r2_storage import R2Storage
                    r2 = R2Storage()
                    
                    # Добавляем "/" в конец префикса для точного совпадения директории
                    # Это гарантирует, что ocr_results/job1 не захватит файлы из ocr_results/job10
                    r2_prefix_normalized = r2_prefix if r2_prefix.endswith('/') else f"{r2_prefix}/"
                    
                    logger.info(f"Удаление файлов из R2 с префиксом: {r2_prefix_normalized}")
                    
                    # Получаем список всех файлов в префиксе
                    files_to_delete = []
                    paginator = r2.s3_client.get_paginator('list_objects_v2')
                    for page in paginator.paginate(Bucket=r2.bucket_name, Prefix=r2_prefix_normalized):
                        if 'Contents' in page:
                            for obj in page['Contents']:
                                key = obj['Key']
                                # Дополнительная проверка: файл должен быть строго внутри директории задачи
                                # (после r2_prefix/ должен быть хотя бы один символ, и не начинаться с другого job_id)
                                if key.startswith(r2_prefix_normalized):
                                    files_to_delete.append({'Key': key})
                                    logger.debug(f"  Будет удален: {key}")
                    
                    # Удаляем все файлы батчами (до 1000 за раз)
                    if files_to_delete:
                        logger.info(f"Найдено {len(files_to_delete)} файлов для удаления")
                        # Batch delete поддерживает до 1000 объектов за раз
                        for i in range(0, len(files_to_delete), 1000):
                            batch = files_to_delete[i:i+1000]
                            r2.s3_client.delete_objects(
                                Bucket=r2.bucket_name,
                                Delete={'Objects': batch}
                            )
                        logger.info(f"✅ Удалено {len(files_to_delete)} файлов из R2 для задачи {job_id[:8]}...")
                    else:
                        logger.info(f"Файлы в R2 не найдены для префикса {r2_prefix_normalized}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка удаления файлов из R2: {e}")
            
            # 3. Удаляем задачу на сервере
            client.delete_job(job_id)
            
            from app.gui.toast import show_toast
            show_toast(self, "Задача и все файлы удалены")
            self._refresh_jobs()
            
        except Exception as e:
            logger.error(f"Ошибка удаления задачи: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить задачу:\n{e}")
    
    def showEvent(self, event):
        """При показе панели обновляем список"""
        super().showEvent(event)
        self._refresh_jobs()
        self.refresh_timer.start(30000)  # 30 секунд (оптимизация)
    
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
        try:
            # Парсим UTC время (может быть как с Z, так и без)
            if dt_str.endswith('Z'):
                dt_utc = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            elif '+' not in dt_str and 'T' in dt_str:
                # ISO формат без timezone - считаем UTC
                dt_utc = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
            else:
                dt_utc = datetime.fromisoformat(dt_str)
            
            # Конвертируем в UTC+3
            utc3 = timezone(timedelta(hours=3))
            dt_local = dt_utc.astimezone(utc3)
            
            return dt_local.strftime("%H:%M %d.%m.%Y")
        except:
            return dt_str

