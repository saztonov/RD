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

try:
    from rd_domain.metadata import __description__, __product__, __version__
except ImportError:
    # Fallback на случай, если metadata.py недоступен
    __version__ = "0.1"
    __product__ = "Core Structure"
    __description__ = "Система структурного анализа и обработки документов"
