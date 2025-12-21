"""
Диалог настройки OCR и выбора папки для результатов
"""

import logging
import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QRadioButton,
                               QGroupBox, QDialogButtonBox, QComboBox, QButtonGroup)
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Загрузка .env для проверки R2
load_dotenv()


class OCRDialog(QDialog):
    """Диалог выбора режима OCR и папки для результатов"""
    
    def __init__(self, parent=None, task_name: str = "", pdf_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Настройка OCR")
        self.setMinimumWidth(550)
        
        self.output_dir = None
        self.base_dir = None
        self.task_name = task_name
        self.pdf_path = pdf_path  # Путь к PDF для сохранения результатов рядом
        self.ocr_backend = "openrouter"  # "openrouter" или "datalab"
        
        # Модели для разных типов блоков
        self.text_model = "qwen/qwen3-vl-30b-a3b-instruct"
        self.table_model = "qwen/qwen3-vl-30b-a3b-instruct"
        self.image_model = "google/gemini-3-flash-preview"
        
        # Datalab настройки
        self.use_datalab = False
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        
        # Выбор OCR бэкенда
        backend_group = QGroupBox("OCR движок для текста и таблиц")
        backend_layout = QVBoxLayout(backend_group)
        
        self.backend_button_group = QButtonGroup(self)
        
        self.datalab_radio = QRadioButton("Datalab Marker API (экономия бюджета)")
        self.openrouter_radio = QRadioButton("OpenRouter (VLM)")
        
        self.backend_button_group.addButton(self.datalab_radio, 0)
        self.backend_button_group.addButton(self.openrouter_radio, 1)
        
        backend_layout.addWidget(self.datalab_radio)
        backend_layout.addWidget(self.openrouter_radio)
        
        # Datalab info
        datalab_info = QLabel(
            "💡 Datalab: склейка блоков в одно изображение для экономии кредитов.\n"
            "   10 блоков = 1 кредит вместо 10"
        )
        datalab_info.setStyleSheet("color: #888; font-size: 10px; margin-left: 20px;")
        backend_layout.addWidget(datalab_info)
        
        # Проверка наличия DATALAB_API_KEY
        datalab_key = os.getenv("DATALAB_API_KEY", "")
        if not datalab_key:
            self.datalab_radio.setEnabled(False)
            self.datalab_radio.setText("Datalab Marker API (DATALAB_API_KEY не найден)")
            self.openrouter_radio.setChecked(True)
        else:
            self.datalab_radio.setChecked(True)
        
        layout.addWidget(backend_group)
        
        # Модели для картинок (Datalab) - показывается только при Datalab
        self.datalab_image_group = QGroupBox("Модель OpenRouter для IMAGE блоков")
        datalab_image_layout = QVBoxLayout(self.datalab_image_group)
        
        datalab_image_info = QLabel("Картинки требуют VLM для описания, Datalab их не обрабатывает")
        datalab_image_info.setStyleSheet("color: #888; font-size: 10px;")
        datalab_image_layout.addWidget(datalab_image_info)
        
        image_model_layout = QHBoxLayout()
        image_model_layout.addWidget(QLabel("Модель:"))
        self.datalab_image_model_combo = QComboBox()
        self.datalab_image_model_combo.addItem("gemini-3-flash (HD-зрение)", "google/gemini-3-flash-preview")
        self.datalab_image_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.datalab_image_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        self.datalab_image_model_combo.setCurrentIndex(0)
        image_model_layout.addWidget(self.datalab_image_model_combo)
        datalab_image_layout.addLayout(image_model_layout)
        
        self.datalab_image_group.setVisible(datalab_key != "")
        layout.addWidget(self.datalab_image_group)
        
        # Модели для типов блоков (OpenRouter) - показывается только при OpenRouter
        self.openrouter_models_group = QGroupBox("Модели для типов блоков (OpenRouter)")
        models_layout = QVBoxLayout(self.openrouter_models_group)
        
        # TEXT
        text_layout = QHBoxLayout()
        text_layout.addWidget(QLabel("Текст:"))
        self.text_model_combo = QComboBox()
        self.text_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.text_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        text_layout.addWidget(self.text_model_combo)
        models_layout.addLayout(text_layout)
        
        # TABLE
        table_layout = QHBoxLayout()
        table_layout.addWidget(QLabel("Таблица:"))
        self.table_model_combo = QComboBox()
        self.table_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.table_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        table_layout.addWidget(self.table_model_combo)
        models_layout.addLayout(table_layout)
        
        # IMAGE
        image_layout = QHBoxLayout()
        image_layout.addWidget(QLabel("Картинка:"))
        self.image_model_combo = QComboBox()
        self.image_model_combo.addItem("gemini-3-flash (HD-зрение)", "google/gemini-3-flash-preview")
        self.image_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.image_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        self.image_model_combo.setCurrentIndex(0)
        image_layout.addWidget(self.image_model_combo)
        models_layout.addLayout(image_layout)
        
        self.openrouter_models_group.setVisible(False)
        layout.addWidget(self.openrouter_models_group)
        
        # Связываем видимость групп моделей с выбором бэкенда
        self.datalab_radio.toggled.connect(self._on_backend_changed)
        self.openrouter_radio.toggled.connect(self._on_backend_changed)
        
        # Информация о задании
        info_group = QGroupBox("Информация")
        info_layout = QVBoxLayout(info_group)
        
        # Имя задачи (из бокового меню)
        task_layout = QHBoxLayout()
        task_layout.addWidget(QLabel("Задание:"))
        self.task_name_label = QLabel(self.task_name if self.task_name else "(не выбрано)")
        self.task_name_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        task_layout.addWidget(self.task_name_label)
        task_layout.addStretch()
        info_layout.addLayout(task_layout)
        
        # R2 Bucket информация
        r2_bucket = os.getenv("R2_BUCKET_NAME", "")
        r2_configured = bool(os.getenv("R2_ACCESS_KEY_ID") and os.getenv("R2_SECRET_ACCESS_KEY"))
        
        r2_layout = QHBoxLayout()
        r2_layout.addWidget(QLabel("R2 Bucket:"))
        if r2_configured and r2_bucket:
            r2_label = QLabel(f"✓ {r2_bucket}")
            r2_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            r2_layout.addWidget(r2_label)
            r2_info = QLabel("(автоматическая загрузка в облако)")
            r2_info.setStyleSheet("color: #888; font-size: 10px;")
            r2_layout.addWidget(r2_info)
        else:
            r2_label = QLabel("✗ не настроен")
            r2_label.setStyleSheet("color: #999;")
            r2_layout.addWidget(r2_label)
            r2_info = QLabel("(только локальное сохранение)")
            r2_info.setStyleSheet("color: #888; font-size: 10px;")
            r2_layout.addWidget(r2_info)
        r2_layout.addStretch()
        info_layout.addLayout(r2_layout)
        
        layout.addWidget(info_group)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Загрузка папки из настроек
        from app.gui.folder_settings_dialog import get_projects_dir
        self.base_dir = get_projects_dir()
    
    def _on_backend_changed(self, checked=None):
        """Показать/скрыть группы моделей в зависимости от выбранного бэкенда"""
        is_datalab = self.datalab_radio.isChecked()
        is_openrouter = self.openrouter_radio.isChecked()
        
        self.datalab_image_group.setVisible(is_datalab)
        self.openrouter_models_group.setVisible(is_openrouter)
    
    def _accept(self):
        """Проверка и принятие"""
        from PySide6.QtWidgets import QMessageBox
        
        if not self.task_name:
            QMessageBox.warning(self, "Ошибка", "Сначала создайте задание в боковом меню")
            return
        
        # Результаты сохраняются в папку где лежит PDF
        if self.pdf_path:
            self.output_dir = str(Path(self.pdf_path).parent)
        elif self.base_dir:
            self.output_dir = self.base_dir
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось определить папку для результатов")
            return
        
        # Определяем backend
        if self.datalab_radio.isChecked():
            self.ocr_backend = "datalab"
            self.use_datalab = True
            self.image_model = self.datalab_image_model_combo.currentData()
        elif self.openrouter_radio.isChecked():
            self.ocr_backend = "openrouter"
            self.use_datalab = False
            self.text_model = self.text_model_combo.currentData()
            self.table_model = self.table_model_combo.currentData()
            self.image_model = self.image_model_combo.currentData()
        else:
            self.ocr_backend = "openrouter"
            self.use_datalab = False
        
        self.accept()

