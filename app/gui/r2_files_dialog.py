"""Диалог для просмотра файлов на R2"""
from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QListWidgetItem,
    QDialogButtonBox, QLabel
)

if TYPE_CHECKING:
    pass


class R2FilesDialog(QDialog):
    """Диалог со списком файлов на R2"""
    
    def __init__(self, r2_base_url: str, r2_files: list, parent=None):
        super().__init__(parent)
        self.r2_base_url = r2_base_url
        self.r2_files = r2_files
        self.setWindowTitle("Файлы на R2 Storage")
        self.setMinimumSize(500, 400)
        self._setup_ui()
    
    def _setup_ui(self):
        """Настроить UI"""
        layout = QVBoxLayout(self)
        
        # Заголовок
        header = QLabel(f"📦 {self.r2_base_url}")
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(header)
        
        # Список файлов
        self.files_list = QListWidget()
        self.files_list.setIconSize(self.files_list.iconSize() * 1.5)
        
        for file_info in self.r2_files:
            icon = file_info.get("icon", "📄")
            name = file_info.get("name", "")
            item = QListWidgetItem(f"{icon}  {name}")
            item.setData(Qt.UserRole, file_info)
            self.files_list.addItem(item)
        
        self.files_list.itemDoubleClicked.connect(self._on_file_double_clicked)
        layout.addWidget(self.files_list)
        
        # Подсказка
        hint = QLabel("💡 Дважды кликните на файл для открытия в браузере")
        hint.setStyleSheet("color: gray; font-size: 10pt; padding: 5px;")
        layout.addWidget(hint)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _on_file_double_clicked(self, item: QListWidgetItem):
        """Обработчик двойного клика на файл"""
        file_info = item.data(Qt.UserRole)
        if file_info:
            file_path = file_info.get("path", "")
            if file_path:
                url = f"{self.r2_base_url}/{file_path}"
                webbrowser.open(url)

