"""
Core Structure - Базовая библиотека

Содержит основную логику для работы с PDF-документами, блоками,
OCR и интеграцией с облачными хранилищами (без GUI).

Модули:
- models: Базовые модели данных (Block, Document, Page)
- pdf_utils: Утилиты для работы с PDF (PyMuPDF)
- annotation_io: Сохранение и загрузка разметки (JSON)
- r2_storage: Интеграция с Cloudflare R2
- ocr: OCR backend'ы (OpenRouter, Datalab)
"""

import sys
from pathlib import Path

# Добавляем корневую директорию в путь для импорта метаданных
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from _metadata import __version__, __product__
except ImportError:
    # Fallback на случай, если _metadata.py недоступен
    __version__ = "0.1"
    __product__ = "Core Structure"




