"""
Диалог настройки OCR и выбора папки для результатов
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

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
        self.ocr_backend = "datalab"  # Всегда используем datalab

        # Модели для разных типов блоков
        self.image_model = "google/gemini-3-flash-preview"
        self.stamp_model = "xiaomi/mimo-v2-flash:free"

        # Datalab настройки
        self.use_datalab = True

        self._setup_ui()

    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)

        # OCR движок для текста и таблиц
        backend_group = QGroupBox("OCR движок для текста и таблиц")
        backend_layout = QVBoxLayout(backend_group)

        # RadioButton для выбора движка
        self.engine_group = QButtonGroup(self)

        self.datalab_radio = QRadioButton("Datalab Marker API (склейка блоков, экономия)")
        self.deepseek_radio = QRadioButton("DeepSeek-OCR-2 (быстрый, markdown)")

        self.engine_group.addButton(self.datalab_radio, 0)
        self.engine_group.addButton(self.deepseek_radio, 1)

        # Проверка наличия ключей
        datalab_key = os.getenv("DATALAB_API_KEY", "")

        self.datalab_radio.setEnabled(bool(datalab_key))
        self.deepseek_radio.setEnabled(True)  # DeepSeek не требует ключа

        # По умолчанию Datalab если есть ключ, иначе DeepSeek
        if datalab_key:
            self.datalab_radio.setChecked(True)
        else:
            self.deepseek_radio.setChecked(True)

        backend_layout.addWidget(self.datalab_radio)
        backend_layout.addWidget(self.deepseek_radio)

        # Инфо-лейблы
        datalab_info = QLabel(
            "   💡 Склейка блоков: 10 блоков = 1 кредит"
        )
        datalab_info.setStyleSheet("color: #888; font-size: 10px; margin-left: 20px;")
        backend_layout.addWidget(datalab_info)

        deepseek_info = QLabel(
            "   ⚡ ~15-20 сек/страница, поддержка PDF, без API ключа"
        )
        deepseek_info.setStyleSheet("color: #888; font-size: 10px; margin-left: 20px;")
        backend_layout.addWidget(deepseek_info)

        # Предупреждение если нет DATALAB_API_KEY
        if not datalab_key:
            error_label = QLabel("⚠️ DATALAB_API_KEY не найден - Datalab недоступен")
            error_label.setStyleSheet("color: #ff6b6b; font-size: 10px; margin-left: 20px;")
            backend_layout.addWidget(error_label)

        layout.addWidget(backend_group)

        # Модели для IMAGE блоков
        models_group = QGroupBox("Модель OpenRouter для IMAGE блоков")
        models_layout = QVBoxLayout(models_group)

        models_info = QLabel(
            "Картинки требуют VLM для описания, Datalab их не обрабатывает"
        )
        models_info.setStyleSheet("color: #888; font-size: 10px;")
        models_layout.addWidget(models_info)

        # Модель для изображений
        image_layout = QHBoxLayout()
        image_layout.addWidget(QLabel("Модель для изображений:"))
        self.image_model_combo = QComboBox()
        self._populate_model_combo(self.image_model_combo)
        image_layout.addWidget(self.image_model_combo)
        models_layout.addLayout(image_layout)

        # Модель для штампов
        stamp_layout = QHBoxLayout()
        stamp_layout.addWidget(QLabel("Модель для штампов:"))
        self.stamp_model_combo = QComboBox()
        self._populate_model_combo(self.stamp_model_combo)
        # Установка xiaomi/mimo-v2-flash:free по умолчанию для штампов
        index = self.stamp_model_combo.findData("xiaomi/mimo-v2-flash:free")
        if index >= 0:
            self.stamp_model_combo.setCurrentIndex(index)
        stamp_layout.addWidget(self.stamp_model_combo)
        models_layout.addLayout(stamp_layout)

        layout.addWidget(models_group)

        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Загрузка папки из настроек
        from app.gui.folder_settings_dialog import get_projects_dir

        self.base_dir = get_projects_dir()

    def _populate_model_combo(self, combo: QComboBox):
        """Заполнить комбобокс моделями"""
        combo.addItem("gemini-3-flash (HD-зрение)", "google/gemini-3-flash-preview")
        combo.addItem("qwen3-vl-30b (быстрая)", "qwen/qwen3-vl-30b-a3b-instruct")
        combo.addItem("qwen3-vl-235b (мощная)", "qwen/qwen3-vl-235b-a22b-instruct")
        combo.addItem("xiaomi mimo-v2-flash (бесплатная)", "xiaomi/mimo-v2-flash:free")
        combo.addItem("minimax m2.1", "minimax/minimax-m2.1")
        combo.addItem("grok-4.1-fast", "x-ai/grok-4.1-fast")
        combo.setCurrentIndex(0)

    def _accept(self):
        """Проверка и принятие"""
        from PySide6.QtWidgets import QMessageBox

        if not self.task_name:
            QMessageBox.warning(
                self, "Ошибка", "Сначала создайте задание в боковом меню"
            )
            return

        # Результаты сохраняются в папку где лежит PDF
        if self.pdf_path:
            self.output_dir = str(Path(self.pdf_path).parent)
        elif self.base_dir:
            self.output_dir = self.base_dir
        else:
            QMessageBox.warning(
                self, "Ошибка", "Не удалось определить папку для результатов"
            )
            return

        # Определяем выбранный OCR движок
        if self.datalab_radio.isChecked():
            self.ocr_backend = "datalab"
            self.use_datalab = True
        elif self.deepseek_radio.isChecked():
            self.ocr_backend = "deepseek"
            self.use_datalab = False
        else:
            self.ocr_backend = "datalab"
            self.use_datalab = True

        self.image_model = self.image_model_combo.currentData()
        self.stamp_model = self.stamp_model_combo.currentData()

        self.accept()
