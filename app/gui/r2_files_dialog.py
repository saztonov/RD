"""Диалог для просмотра файлов на R2"""
from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QListWidgetItem,
    QDialogButtonBox, QLabel, QHBoxLayout, QPushButton
)

if TYPE_CHECKING:
    pass


class R2FilesDialog(QDialog):
    """Диалог со списком файлов на R2"""
    
    def __init__(self, r2_base_url: str, r2_files: list, parent=None):
        super().__init__(parent)
        self.r2_base_url = r2_base_url
        self.r2_files = r2_files
        self.current_path = []  # Стек навигации
        self.setWindowTitle("Файлы на R2 Storage")
        self.setMinimumSize(500, 400)
        self._setup_ui()
    
    def _setup_ui(self):
        """Настроить UI"""
        layout = QVBoxLayout(self)
        
        # Заголовок с навигацией
        nav_layout = QHBoxLayout()
        
        self.back_btn = QPushButton("⬅️ Назад")
        self.back_btn.setMaximumWidth(80)
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        nav_layout.addWidget(self.back_btn)
        
        self.header = QLabel(f"📦 {self.r2_base_url}")
        self.header.setWordWrap(True)
        self.header.setStyleSheet("font-weight: bold; padding: 5px;")
        nav_layout.addWidget(self.header, 1)
        
        layout.addLayout(nav_layout)
        
        # Список файлов
        self.files_list = QListWidget()
        self.files_list.setIconSize(self.files_list.iconSize() * 1.5)
        self.files_list.itemDoubleClicked.connect(self._on_file_double_clicked)
        layout.addWidget(self.files_list)
        
        # Подсказка
        hint = QLabel("💡 Дважды кликните на файл/папку")
        hint.setStyleSheet("color: gray; font-size: 10pt; padding: 5px;")
        layout.addWidget(hint)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Заполняем список файлов
        self._populate_files(self.r2_files)
    
    def _populate_files(self, files: list):
        """Заполнить список файлов"""
        self.files_list.clear()
        
        for file_info in files:
            icon = file_info.get("icon", "📄")
            name = file_info.get("name", "")
            item = QListWidgetItem(f"{icon}  {name}")
            item.setData(Qt.UserRole, file_info)
            self.files_list.addItem(item)
    
    def _on_file_double_clicked(self, item: QListWidgetItem):
        """Обработчик двойного клика на файл"""
        file_info = item.data(Qt.UserRole)
        if not file_info:
            return
        
        # Если это папка - открываем её
        if file_info.get("is_dir"):
            children = file_info.get("children", [])
            self.current_path.append({
                "name": file_info.get("name", ""),
                "files": self._get_current_files()
            })
            self._populate_files(children)
            self._update_header()
            self.back_btn.setEnabled(True)
            return
        
        # Иначе открываем файл в браузере
        file_path = file_info.get("path", "")
        if file_path:
            url = f"{self.r2_base_url}/{file_path}"
            webbrowser.open(url)
    
    def _go_back(self):
        """Вернуться в родительскую папку"""
        if not self.current_path:
            return
        
        prev = self.current_path.pop()
        self._populate_files(prev["files"])
        self._update_header()
        self.back_btn.setEnabled(len(self.current_path) > 0)
    
    def _update_header(self):
        """Обновить заголовок с текущим путём"""
        if self.current_path:
            path_str = "/".join(p["name"] for p in self.current_path)
            self.header.setText(f"📦 {self.r2_base_url}/{path_str}")
        else:
            self.header.setText(f"📦 {self.r2_base_url}")
    
    def _get_current_files(self) -> list:
        """Получить текущий список файлов для сохранения в стек"""
        files = []
        for i in range(self.files_list.count()):
            item = self.files_list.item(i)
            file_info = item.data(Qt.UserRole)
            if file_info:
                files.append(file_info)
        return files
