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
        self.jobs_table.setHorizontalHeaderLabels(["ID", "Документ", "Время начала", "Статус", "Прогресс", "Действия"])
        
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
        
        # Кнопка создания задачи
        buttons_layout = QHBoxLayout()
        
        self.create_job_btn = QPushButton("📤 Отправить выделенные блоки")
        self.create_job_btn.clicked.connect(self._create_job)
        buttons_layout.addWidget(self.create_job_btn)
        
        layout.addLayout(buttons_layout)
        
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
        
        for job in jobs:
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)
            
            # ID (сокращённый)
            job_id = job.id
            short_id = job_id[:8] + "..."
            id_item = QTableWidgetItem(short_id)
            id_item.setData(Qt.UserRole, job_id)
            id_item.setToolTip(job_id)
            self.jobs_table.setItem(row, 0, id_item)
            
            # Документ
            self.jobs_table.setItem(row, 1, QTableWidgetItem(job.document_name))
            
            # Время начала (МСК = UTC+3)
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
            
            # Кнопка информации (для всех статусов)
            info_btn = QPushButton("ℹ️")
            info_btn.setToolTip("Информация о задаче")
            info_btn.setMaximumWidth(40)
            info_btn.clicked.connect(lambda checked, jid=job_id: self._show_job_details(jid))
            actions_layout.addWidget(info_btn)
            
            if job.status == "done":
                # Кнопка открыть результат
                open_btn = QPushButton("📂")
                open_btn.setToolTip("Открыть результат")
                open_btn.setMaximumWidth(40)
                open_btn.clicked.connect(lambda checked, jid=job_id: self._open_result_folder(jid))
                actions_layout.addWidget(open_btn)
            elif job.status == "error":
                # Кнопка показать ошибку
                error_btn = QPushButton("❌")
                error_btn.setToolTip(job.error_message or "Ошибка")
                error_btn.setMaximumWidth(40)
                error_btn.clicked.connect(lambda checked, msg=job.error_message: 
                                         QMessageBox.warning(self, "Ошибка", msg or "Неизвестная ошибка"))
                actions_layout.addWidget(error_btn)
            
            # Кнопка удалить (для всех статусов)
            delete_btn = QPushButton("🗑️")
            delete_btn.setToolTip("Удалить задачу")
            delete_btn.setMaximumWidth(40)
            delete_btn.clicked.connect(lambda checked, jid=job_id: self._delete_job(jid))
            actions_layout.addWidget(delete_btn)
            
            actions_layout.addStretch()
            self.jobs_table.setCellWidget(row, 5, actions_widget)
        
        # Включаем сортировку обратно
        self.jobs_table.setSortingEnabled(True)
    
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
        elif dialog.ocr_backend == "local":
            engine = "local"
        
        try:
            job_info = client.create_job(pdf_path, selected_blocks, engine=engine)
            
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
        """Получить выделенные блоки из PageViewer"""
        blocks = []
        
        # Сначала проверяем выделение в PageViewer
        if hasattr(self.main_window, 'page_viewer'):
            selected = self.main_window.page_viewer.get_selected_blocks()
            if selected:
                return selected
        
        # Если нет выделения в viewer, берём из дерева блоков
        if hasattr(self.main_window, 'blocks_tree'):
            tree = self.main_window.blocks_tree
            selected_items = tree.selectedItems()
            
            for item in selected_items:
                block = item.data(0, Qt.UserRole + 1)
                if block:
                    blocks.append(block)
        
        # Если ничего не выбрано, автоматически берём все блоки текущей страницы
        if not blocks and self.main_window.annotation_document:
            page_data = self.main_window._get_or_create_page(self.main_window.current_page)
            if page_data and page_data.blocks:
                blocks = list(page_data.blocks)
        
        return blocks
    
    def _open_result_folder(self, job_id: str):
        """Скачать и открыть папку с результатами задачи"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            # Определяем папку для сохранения
            # Приоритет 1: Сохранённая папка для этой конкретной задачи
            if job_id in self._job_output_dirs:
                extract_dir = Path(self._job_output_dirs[job_id])
            # Приоритет 2: Последняя использованная папка (если существует)
            elif self._last_output_dir and Path(self._last_output_dir).parent.exists():
                # Создаём подпапку с ID задачи в последней использованной директории
                base_dir = Path(self._last_output_dir).parent
                extract_dir = base_dir / f"result_{job_id[:8]}"
            else:
                # Fallback: временная папка
                import tempfile
                tmp_base = Path(tempfile.gettempdir()) / "rd_ocr_results"
                tmp_base.mkdir(exist_ok=True)
                extract_dir = tmp_base / f"result_{job_id[:8]}"
            
            # Проверяем, был ли результат уже скачан
            result_exists = extract_dir.exists() and (extract_dir / "annotation.json").exists()
            
            if not result_exists:
                # СОЗДАЕМ ПАПКУ
                extract_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Скачивание результата в: {extract_dir}")
                
                # Скачиваем результат
                zip_path = extract_dir / "result.zip"
                client.download_result(job_id, str(zip_path))
                
                # Распаковываем
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_dir)
                
                # Удаляем сам zip
                zip_path.unlink()
                logger.info(f"Результат распакован в: {extract_dir}")
                
                # Удаляем задачу с сервера после успешного скачивания
                try:
                    client.delete_job(job_id)
                    logger.info(f"Задача {job_id} удалена с сервера после скачивания")
                    
                    # Обновляем список задач
                    self._refresh_jobs()
                except Exception as e:
                    logger.warning(f"Не удалось удалить задачу {job_id} с сервера: {e}")
            else:
                logger.info(f"Результат уже скачан, открываем: {extract_dir}")
            
            # Открываем папку
            if sys.platform == 'win32':
                os.startfile(extract_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', extract_dir])
            else:
                subprocess.Popen(['xdg-open', extract_dir])
            
            from app.gui.toast import show_toast
            show_toast(self, "Результат открыт")
            
        except Exception as e:
            logger.error(f"Ошибка открытия результата: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть результат:\n{e}")
    
    def _show_job_details(self, job_id: str):
        """Показать детальную информацию о задаче"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            job_details = client.get_job_details(job_id)
            
            # Добавляем локальный путь из маппинга
            if job_id in self._job_output_dirs:
                job_details["client_output_dir"] = self._job_output_dirs[job_id]
            
            from app.gui.job_details_dialog import JobDetailsDialog
            dialog = JobDetailsDialog(job_details, self)
            dialog.exec()
        except Exception as e:
            logger.error(f"Ошибка получения информации о задаче: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить информацию:\n{e}")
    
    def _delete_job(self, job_id: str):
        """Удалить задачу и её файлы"""
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить задачу {job_id[:8]}...?\n\nБудут удалены все связанные файлы.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        client = self._get_client()
        if client is None:
            return
        
        try:
            client.delete_job(job_id)
            
            # Удаляем маппинг
            if job_id in self._job_output_dirs:
                del self._job_output_dirs[job_id]
                self._save_job_mappings()
            
            from app.gui.toast import show_toast
            show_toast(self, "Задача удалена")
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
            
            return dt_local.strftime("%Y-%m-%d %H:%M:%S")
        except:
            return dt_str

