"""
Core Structure - Базовая библиотека

DEPRECATED: Этот модуль сохранён для обратной совместимости.
Используйте напрямую:
- rd_domain.models - модели данных
- rd_domain.ids - ArmorID
- rd_domain.annotation - работа с разметкой
- rd_pipeline.ocr - OCR backend'ы
- rd_pipeline.output - генерация HTML/Markdown
- rd_adapters.storage - хранилище R2

Legacy модули (будут удалены):
- pdf_utils: Утилиты для работы с PDF (PyMuPDF)
- r2_metadata_cache: Кэш метаданных R2
"""

import sys
from pathlib import Path

# Добавляем корневую директорию в путь для импорта метаданных
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from _metadata import __product__, __version__
except ImportError:
    # Fallback на случай, если _metadata.py недоступен
    __version__ = "0.1"
    __product__ = "Core Structure"
