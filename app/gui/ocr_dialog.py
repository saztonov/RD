"""
Диалог настройки OCR и выбора папки для результатов
"""

import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QRadioButton, QLineEdit, QFileDialog,
                               QGroupBox, QDialogButtonBox, QComboBox)
from PySide6.QtCore import Qt
from pathlib import Path

logger = logging.getLogger(__name__)


class OCRDialog(QDialog):
    """Диалог выбора режима OCR и папки для результатов"""
    
    def __init__(self, parent=None, task_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Настройка OCR")
        self.setMinimumWidth(500)
        
        self.output_dir = None
        self.base_dir = None
        self.task_name = task_name
        self.mode = "blocks"  # "blocks" или "full_page"
        self.vlm_server_url = "http://127.0.0.1:1234/v1"
        self.vlm_model_name = "qwen3-vl-32b-instruct"
        self.ocr_backend = "local"  # "local" или "openrouter"
        self.openrouter_model = "qwen/qwen3-vl-30b-a3b-instruct"
        
        # Модели для разных типов блоков
        self.text_model = "qwen/qwen3-vl-30b-a3b-instruct"
        self.table_model = "qwen/qwen3-vl-30b-a3b-instruct"
        self.image_model = "qwen/qwen3-vl-30b-a3b-instruct"
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        
        # Выбор OCR бэкенда
        backend_group = QGroupBox("OCR движок")
        backend_layout = QVBoxLayout(backend_group)
        
        self.local_radio = QRadioButton("Локальный VLM сервер")
        self.openrouter_radio = QRadioButton("OpenRouter")
        self.local_radio.setChecked(True)
        
        backend_layout.addWidget(self.local_radio)
        backend_layout.addWidget(self.openrouter_radio)
        
        # Выбор модели OpenRouter
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Модель OpenRouter:"))
        self.model_combo = QComboBox()
        self.model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        self.model_combo.setEnabled(False)
        model_layout.addWidget(self.model_combo)
        backend_layout.addLayout(model_layout)
        
        self.openrouter_radio.toggled.connect(lambda checked: self.model_combo.setEnabled(checked))
        
        layout.addWidget(backend_group)
        
        # Режим распознавания
        mode_group = QGroupBox("Режим распознавания")
        mode_layout = QVBoxLayout(mode_group)
        
        self.blocks_radio = QRadioButton("По блокам (учитывает вашу разметку)")
        self.full_page_radio = QRadioButton("Все страницы (автоматическая структура)")
        self.blocks_radio.setChecked(True)
        
        mode_layout.addWidget(self.blocks_radio)
        mode_layout.addWidget(self.full_page_radio)
        
        layout.addWidget(mode_group)
        
        # Выбор моделей для типов блоков (только для OpenRouter)
        models_group = QGroupBox("Модели для типов блоков (OpenRouter)")
        models_layout = QVBoxLayout(models_group)
        
        # TEXT
        text_layout = QHBoxLayout()
        text_layout.addWidget(QLabel("Текст:"))
        self.text_model_combo = QComboBox()
        self.text_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.text_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        self.text_model_combo.setEnabled(False)
        text_layout.addWidget(self.text_model_combo)
        models_layout.addLayout(text_layout)
        
        # TABLE
        table_layout = QHBoxLayout()
        table_layout.addWidget(QLabel("Таблица:"))
        self.table_model_combo = QComboBox()
        self.table_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.table_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        self.table_model_combo.setEnabled(False)
        table_layout.addWidget(self.table_model_combo)
        models_layout.addLayout(table_layout)
        
        # IMAGE
        image_layout = QHBoxLayout()
        image_layout.addWidget(QLabel("Картинка:"))
        self.image_model_combo = QComboBox()
        self.image_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.image_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        self.image_model_combo.setEnabled(False)
        image_layout.addWidget(self.image_model_combo)
        models_layout.addLayout(image_layout)
        
        layout.addWidget(models_group)
        
        # Связываем с выбором OpenRouter
        self.openrouter_radio.toggled.connect(lambda checked: self._update_models_enabled(checked))
        
        # Папка для результатов
        output_group = QGroupBox("Папка для результатов")
        output_layout = QVBoxLayout(output_group)
        
        output_layout.addWidget(QLabel("Будут сохранены:\n• Исходный PDF\n• Разметка (JSON)\n• Кропы и Markdown документ"))
        
        # Имя задачи (из бокового меню)
        task_layout = QHBoxLayout()
        task_layout.addWidget(QLabel("Задание:"))
        self.task_name_label = QLabel(self.task_name if self.task_name else "(не выбрано)")
        self.task_name_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        task_layout.addWidget(self.task_name_label)
        task_layout.addStretch()
        output_layout.addLayout(task_layout)
        
        # Базовая папка
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Папка:"))
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Выберите папку...")
        path_layout.addWidget(self.path_edit)
        
        self.browse_btn = QPushButton("Обзор...")
        self.browse_btn.clicked.connect(self._select_output_dir)
        path_layout.addWidget(self.browse_btn)
        
        output_layout.addLayout(path_layout)
        
        # Итоговый путь
        result_layout = QHBoxLayout()
        result_layout.addWidget(QLabel("Итого:"))
        self.result_path_label = QLabel("")
        self.result_path_label.setStyleSheet("color: #666; font-style: italic;")
        result_layout.addWidget(self.result_path_label)
        output_layout.addLayout(result_layout)
        
        layout.addWidget(output_group)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _update_models_enabled(self, openrouter_enabled):
        """Включить/отключить выбор моделей для типов блоков"""
        self.text_model_combo.setEnabled(openrouter_enabled)
        self.table_model_combo.setEnabled(openrouter_enabled)
        self.image_model_combo.setEnabled(openrouter_enabled)
    
    def _select_output_dir(self):
        """Выбор базовой папки для результатов"""
        dir_path = QFileDialog.getExistingDirectory(self, "Выберите папку для результатов")
        if dir_path:
            self.path_edit.setText(dir_path)
            self.base_dir = dir_path
            self._update_output_path()
    
    def _update_output_path(self):
        """Обновить итоговый путь"""
        if self.base_dir and self.task_name:
            self.output_dir = str(Path(self.base_dir) / self.task_name)
            self.result_path_label.setText(self.output_dir)
        elif self.base_dir:
            self.result_path_label.setText("(задание не выбрано)")
            self.output_dir = None
        else:
            self.result_path_label.setText("")
            self.output_dir = None
    
    def _accept(self):
        """Проверка и принятие"""
        from PySide6.QtWidgets import QMessageBox
        
        if not self.base_dir:
            QMessageBox.warning(self, "Ошибка", "Выберите папку для результатов")
            return
        
        if not self.task_name:
            QMessageBox.warning(self, "Ошибка", "Сначала создайте задание в боковом меню")
            return
        
        self.output_dir = str(Path(self.base_dir) / self.task_name)
        
        # Сохраняем настройки
        self.mode = "blocks" if self.blocks_radio.isChecked() else "full_page"
        self.ocr_backend = "local" if self.local_radio.isChecked() else "openrouter"
        self.openrouter_model = self.model_combo.currentData()
        self.text_model = self.text_model_combo.currentData()
        self.table_model = self.table_model_combo.currentData()
        self.image_model = self.image_model_combo.currentData()
        
        self.accept()

