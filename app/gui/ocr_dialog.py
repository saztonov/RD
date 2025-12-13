"""
Диалог настройки OCR и выбора папки для результатов
"""

import logging
import os
import re
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QRadioButton, QLineEdit, QFileDialog,
                               QGroupBox, QDialogButtonBox, QComboBox, QButtonGroup)
from PySide6.QtCore import QSettings
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Загрузка .env для проверки R2
load_dotenv()


def transliterate_to_latin(text: str) -> str:
    """
    Транслитерация русского текста в латиницу + очистка для URL/путей
    
    Args:
        text: исходный текст (может содержать кириллицу, пробелы, спецсимволы)
    
    Returns:
        Очищенный текст (латиница, подчеркивания, без спецсимволов)
    """
    # Словарь транслитерации (ГОСТ 7.79-2000, система Б)
    cyrillic_to_latin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'C', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }
    
    # Транслитерация по символам
    result = []
    for char in text:
        if char in cyrillic_to_latin:
            result.append(cyrillic_to_latin[char])
        else:
            result.append(char)
    
    transliterated = ''.join(result)
    
    # Заменяем пробелы на подчеркивания
    transliterated = transliterated.replace(' ', '_')
    
    # Удаляем все спецсимволы кроме букв, цифр, подчеркиваний и дефисов
    transliterated = re.sub(r'[^a-zA-Z0-9_\-]', '', transliterated)
    
    # Убираем множественные подчеркивания
    transliterated = re.sub(r'_{2,}', '_', transliterated)
    
    # Убираем подчеркивания в начале и конце
    transliterated = transliterated.strip('_')
    
    return transliterated


class OCRDialog(QDialog):
    """Диалог выбора режима OCR и папки для результатов"""
    
    def __init__(self, parent=None, task_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Настройка OCR")
        self.setMinimumWidth(550)
        
        self.output_dir = None
        self.base_dir = None
        self.task_name = task_name
        self.mode = "blocks"  # "blocks" или "full_page"
        self.vlm_server_url = ""  # Не используется (ngrok endpoint)
        self.vlm_model_name = "qwen3-vl-32b-instruct"
        self.ocr_backend = "local"  # "local", "openrouter" или "datalab"
        self.openrouter_model = "qwen/qwen3-vl-30b-a3b-instruct"
        
        # Модели для разных типов блоков
        self.text_model = "qwen/qwen3-vl-30b-a3b-instruct"
        self.table_model = "qwen/qwen3-vl-30b-a3b-instruct"
        self.image_model = "qwen/qwen3-vl-30b-a3b-instruct"
        
        # Batch оптимизация
        self.use_batch_ocr = True
        
        # Datalab настройки
        self.use_datalab = False
        self.datalab_image_backend = "local"  # "local" или "openrouter" для IMAGE блоков
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        
        # Выбор OCR бэкенда
        backend_group = QGroupBox("OCR движок для текста и таблиц")
        backend_layout = QVBoxLayout(backend_group)
        
        self.backend_button_group = QButtonGroup(self)
        
        self.datalab_radio = QRadioButton("Datalab Marker API (экономия бюджета)")
        self.local_radio = QRadioButton("Локальный VLM сервер")
        self.openrouter_radio = QRadioButton("OpenRouter (VLM)")
        
        self.backend_button_group.addButton(self.datalab_radio, 0)
        self.backend_button_group.addButton(self.local_radio, 1)
        self.backend_button_group.addButton(self.openrouter_radio, 2)
        
        backend_layout.addWidget(self.datalab_radio)
        backend_layout.addWidget(self.local_radio)
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
            self.local_radio.setChecked(True)
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
        self.datalab_image_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.datalab_image_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        self.datalab_image_model_combo.setCurrentIndex(1)
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
        self.image_model_combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        self.image_model_combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        self.image_model_combo.setCurrentIndex(1)
        image_layout.addWidget(self.image_model_combo)
        models_layout.addLayout(image_layout)
        
        self.openrouter_models_group.setVisible(False)
        layout.addWidget(self.openrouter_models_group)
        
        # Связываем видимость групп моделей с выбором бэкенда
        self.datalab_radio.toggled.connect(self._on_backend_changed)
        self.openrouter_radio.toggled.connect(self._on_backend_changed)
        self.local_radio.toggled.connect(self._on_backend_changed)
        
        # Папка для результатов
        output_group = QGroupBox("Папка для результатов")
        output_layout = QVBoxLayout(output_group)
        
        output_layout.addWidget(QLabel("Будут сохранены:\n• Исходный PDF\n• Разметка (JSON)\n• Кропы и Markdown документ"))
        
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
        output_layout.addLayout(r2_layout)
        
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
        
        # Загрузка сохраненной папки
        settings = QSettings("RDApp", "OCRDialog")
        last_dir = settings.value("last_output_dir", "")
        if last_dir and os.path.exists(last_dir):
            self.path_edit.setText(last_dir)
            self.base_dir = last_dir
            self._update_output_path()
    
    def _on_backend_changed(self, checked=None):
        """Показать/скрыть группы моделей в зависимости от выбранного бэкенда"""
        is_datalab = self.datalab_radio.isChecked()
        is_openrouter = self.openrouter_radio.isChecked()
        
        self.datalab_image_group.setVisible(is_datalab)
        self.openrouter_models_group.setVisible(is_openrouter)
    
    def _select_output_dir(self):
        """Выбор базовой папки для результатов"""
        dir_path = QFileDialog.getExistingDirectory(self, "Выберите папку для результатов")
        if dir_path:
            self.path_edit.setText(dir_path)
            self.base_dir = dir_path
            self._update_output_path()
            # Сохранение выбранной папки
            settings = QSettings("RDApp", "OCRDialog")
            settings.setValue("last_output_dir", dir_path)
    
    def _update_output_path(self):
        """Обновить итоговый путь (показ примера с timestamp)"""
        if self.base_dir and self.task_name:
            # Показываем пример с транслитерированным названием
            safe_task_name = transliterate_to_latin(self.task_name)
            example_path = str(Path(self.base_dir) / f"{safe_task_name}_YYYYMMDD_HHMMSS")
            self.result_path_label.setText(example_path)
        elif self.base_dir:
            self.result_path_label.setText("(задание не выбрано)")
        else:
            self.result_path_label.setText("")
    
    def _accept(self):
        """Проверка и принятие"""
        from PySide6.QtWidgets import QMessageBox
        from datetime import datetime
        
        if not self.base_dir:
            QMessageBox.warning(self, "Ошибка", "Выберите папку для результатов")
            return
        
        if not self.task_name:
            QMessageBox.warning(self, "Ошибка", "Сначала создайте задание в боковом меню")
            return
        
        # Добавляем timestamp для уникальности пути
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Транслитерируем название задания для безопасных URL/путей
        safe_task_name = transliterate_to_latin(self.task_name)
        unique_name = f"{safe_task_name}_{timestamp}"
        self.output_dir = str(Path(self.base_dir) / unique_name)
        
        # Сохраняем настройки
        self.mode = "blocks"  # Всегда по блокам
        self.use_batch_ocr = True  # Всегда с batch-оптимизацией
        
        # Определяем backend
        if self.datalab_radio.isChecked():
            self.ocr_backend = "datalab"
            self.use_datalab = True
            self.datalab_image_backend = "openrouter"  # Всегда OpenRouter для картинок
            self.image_model = self.datalab_image_model_combo.currentData()
        elif self.openrouter_radio.isChecked():
            self.ocr_backend = "openrouter"
            self.use_datalab = False
            self.text_model = self.text_model_combo.currentData()
            self.table_model = self.table_model_combo.currentData()
            self.image_model = self.image_model_combo.currentData()
        else:
            self.ocr_backend = "local"
            self.use_datalab = False
        
        self.accept()

