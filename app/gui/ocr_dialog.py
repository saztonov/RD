"""
Диалог настройки OCR и выбора папки для результатов
"""

import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QRadioButton, QLineEdit, QFileDialog,
                               QGroupBox, QDialogButtonBox)
from PySide6.QtCore import Qt
from pathlib import Path

logger = logging.getLogger(__name__)


class OCRDialog(QDialog):
    """Диалог выбора режима OCR и папки для результатов"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка OCR")
        self.setMinimumWidth(500)
        
        self.output_dir = None
        self.mode = "blocks"  # "blocks" или "full_page"
        self.vlm_server_url = "http://127.0.0.1:1234/v1"
        self.vlm_model_name = "qwen3-vl-32b-instruct"
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        
        # Режим распознавания
        mode_group = QGroupBox("Режим распознавания")
        mode_layout = QVBoxLayout(mode_group)
        
        self.blocks_radio = QRadioButton("По блокам (учитывает вашу разметку)")
        self.full_page_radio = QRadioButton("Все страницы (автоматическая структура)")
        self.blocks_radio.setChecked(True)
        
        mode_layout.addWidget(self.blocks_radio)
        mode_layout.addWidget(self.full_page_radio)
        
        layout.addWidget(mode_group)
        
        # Папка для результатов
        output_group = QGroupBox("Папка для результатов")
        output_layout = QVBoxLayout(output_group)
        
        output_layout.addWidget(QLabel("Будут сохранены:\n• Исходный PDF\n• Разметка (JSON)\n• Кропы и Markdown документ"))
        
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Выберите папку...")
        path_layout.addWidget(self.path_edit)
        
        self.browse_btn = QPushButton("Обзор...")
        self.browse_btn.clicked.connect(self._select_output_dir)
        path_layout.addWidget(self.browse_btn)
        
        output_layout.addLayout(path_layout)
        
        layout.addWidget(output_group)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _select_output_dir(self):
        """Выбор папки для результатов"""
        dir_path = QFileDialog.getExistingDirectory(self, "Выберите папку для результатов")
        if dir_path:
            self.path_edit.setText(dir_path)
            self.output_dir = dir_path
    
    def _accept(self):
        """Проверка и принятие"""
        if not self.output_dir:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Ошибка", "Выберите папку для результатов")
            return
        
        # Сохраняем настройки
        self.mode = "blocks" if self.blocks_radio.isChecked() else "full_page"
        
        self.accept()

