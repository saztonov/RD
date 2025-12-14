"""Панель для управления Remote OCR задачами"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDockWidget, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFileDialog, QLabel, QProgressBar
)

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class RemoteOCRPanel(QDockWidget):
    """Dock-панель для Remote OCR задач"""
    
    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__("Remote OCR Jobs", parent)
        self.main_window = main_window
        self._client = None
        self._current_document_id = None
        self._last_output_dir = None
        self._last_engine = None
        self._job_output_dirs = {}  # Маппинг job_id -> output_dir
        self._config_file = Path.home() / ".rd" / "remote_ocr_jobs.json"
        self._job_statuses = {}  # Отслеживание статусов для автоскачивания
        
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
        self.setMinimumWidth(300)
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
        """Обновить список задач"""
        client = self._get_client()
        if client is None:
            self.status_label.setText("🔴 Ошибка клиента")
            return
        
        # Показываем ВСЕ задачи (не фильтруем по document_id)
        try:
            jobs = client.list_jobs(document_id=None)
            
            # Проверяем новые завершённые задачи для автоскачивания
            for job in jobs:
                old_status = self._job_statuses.get(job.id)
                new_status = job.status
                
                # Если статус изменился на "done" - автоматически скачиваем
                if old_status != "done" and new_status == "done":
                    logger.info(f"Задача {job.id} завершена, автоскачивание...")
                    self._auto_download_result(job.id)
                
                # Обновляем статус
                self._job_statuses[job.id] = new_status
            
            self._update_table(jobs)
            self.status_label.setText("🟢 Подключено")
        except Exception as e:
            logger.error(f"Ошибка получения списка задач: {e}")
            self.status_label.setText("🔴 Сервер недоступен")
    
    def _update_table(self, jobs):
        """Обновить таблицу задач"""
        # Отключаем сортировку на время обновления
        self.jobs_table.setSortingEnabled(False)
        self.jobs_table.setRowCount(0)
        
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
        try:
            # Сохраняем текущую аннотацию в кеш перед переключением
            self.main_window._save_current_annotation_to_cache()
            
            # Сбрасываем маркеры проекта/файла (иначе система путается при последующем переключении)
            self.main_window._current_project_id = None
            self.main_window._current_file_index = -1
            
            # Сохраняем зум перед переключением
            if hasattr(self.main_window, 'navigation_manager') and self.main_window.navigation_manager:
                self.main_window.navigation_manager.save_current_zoom()
            
            # Определяем папку результата
            if job_id in self._job_output_dirs:
                extract_dir = Path(self._job_output_dirs[job_id])
            elif self._last_output_dir and Path(self._last_output_dir).parent.exists():
                base_dir = Path(self._last_output_dir).parent
                extract_dir = base_dir / f"result_{job_id[:8]}"
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()
            else:
                import tempfile
                tmp_base = Path(tempfile.gettempdir()) / "rd_ocr_results"
                tmp_base.mkdir(exist_ok=True)
                extract_dir = tmp_base / f"result_{job_id[:8]}"
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()

            annotation_path = extract_dir / "annotation.json"
            pdf_path = extract_dir / "document.pdf"

            # Если результата нет локально — пробуем докачать (R2)
            if not annotation_path.exists() or not pdf_path.exists():
                self._auto_download_result(job_id)

            if not annotation_path.exists():
                QMessageBox.warning(self, "Нет результата", "annotation.json не найден (задача не готова или результат не скачан).")
                return

            from rd_core.annotation_io import AnnotationIO
            loaded_doc = AnnotationIO.load_annotation(str(annotation_path))
            if not loaded_doc:
                QMessageBox.critical(self, "Ошибка", "Не удалось загрузить annotation.json")
                return

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
        
        try:
            job_info = client.create_job(
                pdf_path,
                selected_blocks,
                task_name=self.main_window.project_manager.get_active_project().name if self.main_window.project_manager.get_active_project() else "",
                engine=engine,
                text_model=getattr(dialog, "text_model", None),
                table_model=getattr(dialog, "table_model", None),
                image_model=getattr(dialog, "image_model", None),
            )
            
            # Сохраняем маппинг job_id -> output_dir
            self._job_output_dirs[job_info.id] = dialog.output_dir
            self._save_job_mappings()
            
            from app.gui.toast import show_toast
            show_toast(self, f"Задача создана: {job_info.id[:8]}...", duration=2500)
            self._refresh_jobs()
        except Exception as e:
            logger.error(f"Ошибка создания задачи: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать задачу:\n{e}")
    
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
    
    def _auto_download_result(self, job_id: str):
        """Автоматически скачать результат из R2"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            # Получаем детали задачи (включая r2_prefix)
            job_details = client.get_job_details(job_id)
            r2_prefix = job_details.get("r2_prefix")
            
            if not r2_prefix:
                logger.warning(f"Задача {job_id} не имеет r2_prefix, пропускаем автоскачивание")
                return
            
            # Определяем папку для сохранения
            if job_id in self._job_output_dirs:
                extract_dir = Path(self._job_output_dirs[job_id])
            elif self._last_output_dir and Path(self._last_output_dir).parent.exists():
                base_dir = Path(self._last_output_dir).parent
                extract_dir = base_dir / f"result_{job_id[:8]}"
            else:
                import tempfile
                tmp_base = Path(tempfile.gettempdir()) / "rd_ocr_results"
                tmp_base.mkdir(exist_ok=True)
                extract_dir = tmp_base / f"result_{job_id[:8]}"
            
            # Сохраняем маппинг
            if job_id not in self._job_output_dirs:
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()
            
            # Проверяем, был ли уже скачан
            result_exists = extract_dir.exists() and (extract_dir / "annotation.json").exists()
            
            if not result_exists:
                extract_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Автоскачивание результата из R2 в: {extract_dir}")
                
                # Инициализируем R2Storage
                from rd_core.r2_storage import R2Storage
                r2 = R2Storage()
                
                # Скачиваем основные файлы
                main_files = ["annotation.json", "result.md", "document.pdf"]
                for filename in main_files:
                    remote_key = f"{r2_prefix}/{filename}"
                    local_path = extract_dir / filename
                    r2.download_file(remote_key, str(local_path))
                
                # Скачиваем кропы из папки crops/
                crops_dir = extract_dir / "crops"
                crops_dir.mkdir(exist_ok=True)
                
                # Получаем список всех файлов в R2 с префиксом crops/
                crops_prefix = f"{r2_prefix}/crops/"
                crop_files = r2.list_by_prefix(crops_prefix)
                
                for remote_key in crop_files:
                    # Извлекаем имя файла
                    filename = remote_key.split("/")[-1]
                    if filename:  # Пропускаем директории
                        local_path = crops_dir / filename
                        r2.download_file(remote_key, str(local_path))
                
                logger.info(f"✅ Результат автоматически скачан из R2: {extract_dir}")
                
                from app.gui.toast import show_toast
                show_toast(self.main_window, f"Результат скачан: {job_id[:8]}...")
            else:
                logger.debug(f"Результат уже скачан: {extract_dir}")
                
        except Exception as e:
            logger.error(f"Ошибка автоскачивания результата {job_id}: {e}")
    
    def _show_job_details(self, job_id: str):
        """Показать детальную информацию о задаче"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            job_details = client.get_job_details(job_id)
            
            # Определяем локальный путь
            if job_id not in self._job_output_dirs:
                # Определяем путь по тем же правилам, что и при автоскачивании
                if self._last_output_dir and Path(self._last_output_dir).parent.exists():
                    base_dir = Path(self._last_output_dir).parent
                    extract_dir = base_dir / f"result_{job_id[:8]}"
                else:
                    import tempfile
                    tmp_base = Path(tempfile.gettempdir()) / "rd_ocr_results"
                    extract_dir = tmp_base / f"result_{job_id[:8]}"
                
                # Сохраняем маппинг
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()
            
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

