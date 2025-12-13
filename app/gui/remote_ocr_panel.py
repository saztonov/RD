"""Панель для управления Remote OCR задачами"""
from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
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
    
    result_applied = Signal(str)  # job_id
    
    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__("Remote OCR Jobs", parent)
        self.main_window = main_window
        self._client = None
        self._current_document_id = None
        
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
        self.jobs_table.setHorizontalHeaderLabels(["ID", "Документ", "Статус", "Прогресс", "Действия", "Результат"])
        
        header = self.jobs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
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
            self.jobs_table.setItem(row, 2, status_item)
            
            # Прогресс
            progress_text = f"{int(job.progress * 100)}%"
            self.jobs_table.setItem(row, 3, QTableWidgetItem(progress_text))
            
            # Кнопка действия (применить/ошибка)
            if job.status == "done":
                btn = QPushButton("📥 Применить")
                btn.clicked.connect(lambda checked, jid=job_id: self._download_and_apply(jid))
                self.jobs_table.setCellWidget(row, 4, btn)
            elif job.status == "error":
                btn = QPushButton("ℹ️")
                btn.setToolTip(job.error_message or "Ошибка")
                btn.clicked.connect(lambda checked, msg=job.error_message: 
                                   QMessageBox.warning(self, "Ошибка", msg or "Неизвестная ошибка"))
                self.jobs_table.setCellWidget(row, 4, btn)
            
            # Кнопка открытия результата (для готовых задач)
            if job.status == "done":
                open_btn = QPushButton("📂 Открыть")
                open_btn.clicked.connect(lambda checked, jid=job_id: self._open_result_folder(jid))
                self.jobs_table.setCellWidget(row, 5, open_btn)
    
    def _create_job(self):
        """Создать новую задачу OCR"""
        # Проверяем наличие PDF
        if not self.main_window.pdf_document or not self.main_window.annotation_document:
            QMessageBox.warning(self, "Ошибка", "Откройте PDF документ")
            return
        
        pdf_path = self.main_window.annotation_document.pdf_path
        if not pdf_path or not Path(pdf_path).exists():
            QMessageBox.warning(self, "Ошибка", "PDF файл не найден")
            return
        
        # Собираем выделенные блоки
        selected_blocks = self._get_selected_blocks()
        if not selected_blocks:
            QMessageBox.warning(self, "Ошибка", "Выберите блоки для распознавания")
            return
        
        client = self._get_client()
        if client is None:
            QMessageBox.warning(self, "Ошибка", "Клиент не инициализирован")
            return
        
        try:
            job_info = client.create_job(pdf_path, selected_blocks)
            QMessageBox.information(
                self,
                "Задача создана",
                f"ID: {job_info.id}\nСтатус: {job_info.status}"
            )
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
        
        # Если ничего не выбрано, предлагаем отправить все блоки текущей страницы
        if not blocks and self.main_window.annotation_document:
            page_data = self.main_window._get_or_create_page(self.main_window.current_page)
            if page_data and page_data.blocks:
                reply = QMessageBox.question(
                    self,
                    "Подтверждение",
                    f"Нет выделенных блоков. Отправить все {len(page_data.blocks)} блоков текущей страницы?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    blocks = list(page_data.blocks)
        
        return blocks
    
    def _download_and_apply(self, job_id: str):
        """Скачать и применить результат"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            # Скачиваем во временную директорию
            import tempfile
            with tempfile.TemporaryDirectory() as tmp_dir:
                zip_path = Path(tmp_dir) / "result.zip"
                client.download_result(job_id, str(zip_path))
                
                # Распаковываем
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(tmp_dir)
                
                result_json_path = Path(tmp_dir) / "result.json"
                if not result_json_path.exists():
                    QMessageBox.warning(self, "Ошибка", "result.json не найден в архиве")
                    return
                
                with open(result_json_path, 'r', encoding='utf-8') as f:
                    result_data = json.load(f)
                
                # Применяем результаты к блокам
                applied_count = self._apply_results(result_data)
                
                QMessageBox.information(
                    self,
                    "Результат применён",
                    f"Обновлено блоков: {applied_count}"
                )
                
                self.result_applied.emit(job_id)
                
        except Exception as e:
            logger.error(f"Ошибка загрузки результата: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить результат:\n{e}")
    
    def _apply_results(self, result_data: list) -> int:
        """Применить результаты OCR к блокам документа"""
        if not self.main_window.annotation_document:
            return 0
        
        # Создаём индекс результатов по block_id
        results_by_id = {r["block_id"]: r for r in result_data}
        
        applied = 0
        for page in self.main_window.annotation_document.pages:
            for block in page.blocks:
                if block.id in results_by_id:
                    text = results_by_id[block.id].get("text", "")
                    if text:
                        block.ocr_text = text
                        applied += 1
        
        # Обновляем UI
        if hasattr(self.main_window, 'blocks_tree_manager'):
            self.main_window.blocks_tree_manager.update_blocks_tree()
        
        if hasattr(self.main_window, 'page_viewer'):
            self.main_window.page_viewer.update()
        
        return applied
    
    def _open_result_folder(self, job_id: str):
        """Открыть папку с результатами задачи"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            # Получаем информацию о задаче
            job = client.get_job(job_id)
            
            # Скачиваем результат во временную папку
            import tempfile
            import subprocess
            import sys
            
            with tempfile.TemporaryDirectory() as tmp_dir:
                zip_path = Path(tmp_dir) / "result.zip"
                client.download_result(job_id, str(zip_path))
                
                # Создаём папку для распаковки
                extract_dir = Path(tmp_dir) / f"result_{job_id[:8]}"
                extract_dir.mkdir(exist_ok=True)
                
                # Распаковываем
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_dir)
                
                # Открываем папку в проводнике
                if sys.platform == 'win32':
                    os.startfile(extract_dir)
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', extract_dir])
                else:
                    subprocess.Popen(['xdg-open', extract_dir])
                
                QMessageBox.information(
                    self,
                    "Результат открыт",
                    f"Папка с результатами открыта во временной директории:\n{extract_dir}\n\n"
                    "Файлы будут удалены после закрытия приложения."
                )
                
        except Exception as e:
            logger.error(f"Ошибка открытия результата: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть результат:\n{e}")
    
    def showEvent(self, event):
        """При показе панели обновляем список"""
        super().showEvent(event)
        self._refresh_jobs()
        self.refresh_timer.start(30000)  # 30 секунд (оптимизация)
    
    def hideEvent(self, event):
        """При скрытии останавливаем таймер"""
        super().hideEvent(event)
        self.refresh_timer.stop()

