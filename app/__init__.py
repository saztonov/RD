"""
Core Structure - Система структурного анализа и обработки документов

Desktop-приложение для интеллектуального анализа и аннотирования PDF-документов
с поддержкой удалённого OCR, иерархического управления проектами и экспорта в Markdown.

Основные возможности:
- Ручная и автоматическая разметка блоков (text/table/image)
- Полигональная разметка произвольных фигур
- Удалённая обработка OCR через Celery + Redis
- Иерархическое управление проектами в Supabase
- Интеграция с R2 Storage для хранения файлов
- Экспорт в Markdown и PDF
"""

import sys
from pathlib import Path

# Добавляем корневую директорию в путь для импорта метаданных
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from _metadata import __version__, __product__, __description__
except ImportError:
    # Fallback на случай, если _metadata.py недоступен
    __version__ = "0.1"
    __product__ = "Core Structure"
    __description__ = "Система структурного анализа и обработки документов"








