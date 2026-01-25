"""
Настройки OCR сервера.

Компоненты:
- models.py - OCRSettings dataclass
- dialog.py - OCRSettingsDialog
"""
from .dialog import OCRSettingsDialog
from .models import OCRSettings

__all__ = ["OCRSettings", "OCRSettingsDialog"]
