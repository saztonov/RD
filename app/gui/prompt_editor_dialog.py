"""
Диалог редактирования промтов
Промпты хранятся в R2 Storage (rd1/prompts/) в JSON формате с полями system и user
"""

import json
import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTextEdit, QPushButton, 
                               QLabel, QMessageBox, QHBoxLayout, QSplitter)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class PromptEditorDialog(QDialog):
    """Диалог редактирования промта из R2 (system + user)"""
    
    def __init__(self, parent, title: str, prompt_data: dict = None, prompt_key: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"R2: {title}")
        self.resize(800, 600)
        self.prompt_key = prompt_key
        
        # Парсим данные промта
        if prompt_data is None:
            prompt_data = {}
        self.system_text = prompt_data.get("system", "")
        self.user_text = prompt_data.get("user", "")
        
        layout = QVBoxLayout()
        
        # Заголовок
        label = QLabel(f"<b>{title}</b>")
        layout.addWidget(label)
        
        # Путь в R2
        r2_path = f"rd1/prompts/{prompt_key}.json" if prompt_key else "rd1/prompts/"
        path_label = QLabel(f"<i style='color: #666;'>📁 {r2_path}</i>")
        layout.addWidget(path_label)
        
        # Splitter для двух полей
        splitter = QSplitter(Qt.Vertical)
        
        # System/Role промт
        system_widget = QVBoxLayout()
        system_label = QLabel("<b>System / Role</b> <i style='color:#888'>(роль и контекст для модели)</i>")
        
        self.system_edit = QTextEdit()
        self.system_edit.setPlainText(self.system_text)
        self.system_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.system_edit.setPlaceholderText("Опишите роль модели, контекст задачи, общие правила...")
        
        from PySide6.QtWidgets import QWidget
        system_container = QWidget()
        sys_layout = QVBoxLayout(system_container)
        sys_layout.setContentsMargins(0, 0, 0, 0)
        sys_layout.addWidget(system_label)
        sys_layout.addWidget(self.system_edit)
        splitter.addWidget(system_container)
        
        # User Input промт
        user_widget = QVBoxLayout()
        user_label = QLabel("<b>User Input</b> <i style='color:#888'>(инструкция для конкретного блока)</i>")
        
        self.user_edit = QTextEdit()
        self.user_edit.setPlainText(self.user_text)
        self.user_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.user_edit.setPlaceholderText("Инструкция что делать с изображением блока...")
        
        user_container = QWidget()
        usr_layout = QVBoxLayout(user_container)
        usr_layout.setContentsMargins(0, 0, 0, 0)
        usr_layout.addWidget(user_label)
        usr_layout.addWidget(self.user_edit)
        splitter.addWidget(user_container)
        
        layout.addWidget(splitter)
        
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
    
    def get_prompt_data(self) -> dict:
        """Получить данные промта как dict"""
        return {
            "system": self.system_edit.toPlainText(),
            "user": self.user_edit.toPlainText()
        }
    
    def get_prompt_text(self) -> str:
        """Для совместимости - возвращает JSON"""
        return json.dumps(self.get_prompt_data(), ensure_ascii=False, indent=2)

