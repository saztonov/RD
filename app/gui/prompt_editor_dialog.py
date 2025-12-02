"""
Диалог редактирования промтов для типов и категорий
"""

import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTextEdit, QPushButton, 
                               QLabel, QMessageBox, QHBoxLayout)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class PromptEditorDialog(QDialog):
    """Диалог редактирования промта"""
    
    def __init__(self, parent, title: str, prompt_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 500)
        self.prompt_text = prompt_text
        
        layout = QVBoxLayout()
        
        # Заголовок
        label = QLabel(f"<b>{title}</b>")
        layout.addWidget(label)
        
        # Текстовое поле для промта
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(prompt_text)
        layout.addWidget(self.text_edit)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
    
    def get_prompt_text(self) -> str:
        """Получить текст промта"""
        return self.text_edit.toPlainText()

