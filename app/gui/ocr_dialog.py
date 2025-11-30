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
        self.mode = "full_page"  # "blocks" или "full_page"
        self.engine = "local_vlm"  # "local_vlm" или "chandra"
        self.vlm_server_url = "http://127.0.0.1:1234/v1"
        self.vlm_model_name = "qwen3-vl-32b-instruct"
        self.chandra_method = "hf"
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        
        # Режим распознавания
        mode_group = QGroupBox("Режим распознавания")
        mode_layout = QVBoxLayout(mode_group)
        
        self.blocks_radio = QRadioButton("По блокам (учитывает вашу разметку)")
        self.full_page_radio = QRadioButton("Все страницы (автоматическая структура)")
        self.full_page_radio.setChecked(True)
        
        mode_layout.addWidget(self.blocks_radio)
        mode_layout.addWidget(self.full_page_radio)
        
        layout.addWidget(mode_group)
        
        # Движок OCR
        engine_group = QGroupBox("Движок OCR")
        engine_layout = QVBoxLayout(engine_group)
        
        # VLM
        self.vlm_radio = QRadioButton("Локальный VLM сервер (Qwen3-VL и др.)")
        self.vlm_radio.setChecked(True)
        engine_layout.addWidget(self.vlm_radio)
        
        vlm_settings_layout = QVBoxLayout()
        vlm_settings_layout.setContentsMargins(20, 0, 0, 0)
        
        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("URL:"))
        self.server_edit = QLineEdit("http://127.0.0.1:1234/v1")
        server_layout.addWidget(self.server_edit)
        vlm_settings_layout.addLayout(server_layout)
        
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Модель:"))
        self.model_edit = QLineEdit("qwen3-vl-32b-instruct")
        model_layout.addWidget(self.model_edit)
        vlm_settings_layout.addLayout(model_layout)
        
        engine_layout.addLayout(vlm_settings_layout)
        
        # Chandra
        self.chandra_radio = QRadioButton("Chandra OCR")
        engine_layout.addWidget(self.chandra_radio)
        
        chandra_settings_layout = QHBoxLayout()
        chandra_settings_layout.setContentsMargins(20, 0, 0, 0)
        
        self.chandra_hf_radio = QRadioButton("HuggingFace")
        self.chandra_hf_radio.setChecked(True)
        self.chandra_vllm_radio = QRadioButton("vLLM")
        
        chandra_settings_layout.addWidget(self.chandra_hf_radio)
        chandra_settings_layout.addWidget(self.chandra_vllm_radio)
        chandra_settings_layout.addStretch()
        
        engine_layout.addLayout(chandra_settings_layout)
        
        layout.addWidget(engine_group)
        
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
        self.engine = "local_vlm" if self.vlm_radio.isChecked() else "chandra"
        
        if self.engine == "local_vlm":
            self.vlm_server_url = self.server_edit.text().strip()
            self.vlm_model_name = self.model_edit.text().strip()
        else:
            self.chandra_method = "hf" if self.chandra_hf_radio.isChecked() else "vllm"
        
        self.accept()

