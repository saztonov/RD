"""
Диалог редактирования промтов для типов и категорий
Промпты хранятся в R2 Storage (rd1/prompts/)
"""

import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTextEdit, QPushButton, 
                               QLabel, QMessageBox, QHBoxLayout)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class PromptEditorDialog(QDialog):
    """Диалог редактирования промта из R2"""
    
    def __init__(self, parent, title: str, prompt_text: str = "", prompt_key: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"R2: {title}")
        self.resize(700, 500)
        self.prompt_text = prompt_text
        self.prompt_key = prompt_key
        
        layout = QVBoxLayout()
        
        # Заголовок
        label = QLabel(f"<b>{title}</b>")
        layout.addWidget(label)
        
        # Путь в R2
        r2_path = f"rd1/prompts/{prompt_key}.txt" if prompt_key else "rd1/prompts/"
        path_label = QLabel(f"<i style='color: #666;'>📁 {r2_path}</i>")
        layout.addWidget(path_label)
        
        # Текстовое поле для промта
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(prompt_text)
        self.text_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        layout.addWidget(self.text_edit)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        
        save_btn = QPushButton("💾 Сохранить в R2")
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

