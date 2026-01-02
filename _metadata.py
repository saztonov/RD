"""
Core Structure - Централизованные метаданные проекта

Этот модуль содержит общую информацию о продукте,
которая используется во всех частях системы.
"""

__product__ = "Core Structure"
__version__ = "0.1"
__description__ = "Система структурного анализа и обработки документов"
__author__ = "Core Structure Team"
__license__ = "MIT"
__url__ = "https://github.com/your-org/core-structure"
__status__ = "Alpha"
__python_requires__ = ">=3.11"

# Детальное описание
__long_description__ = """
Core Structure - это интеллектуальная система структурного анализа и обработки 
документов, предназначенная для профессиональной работы с PDF-файлами. 

Система обеспечивает комплексный подход к распознаванию, аннотированию 
и структурированию документов с использованием современных технологий OCR 
и облачных хранилищ.

Основные возможности:
- Ручная и автоматическая разметка блоков (text/table/image)
- Полигональная разметка произвольных фигур
- Удалённая обработка OCR через Celery + Redis
- Иерархическое управление проектами в Supabase
- Интеграция с R2 Storage для хранения файлов
- Экспорт в Markdown и PDF
"""

# Технологический стек
__tech_stack__ = {
    "python": "3.11+",
    "gui": "PySide6",
    "storage": "Cloudflare R2 + Supabase",
    "ocr": "OpenRouter, Datalab",
    "queue": "Celery + Redis",
}

# Информационная строка для отображения
def get_version_info():
    """Возвращает полную информацию о версии"""
    return f"{__product__} v{__version__} ({__status__})"

def get_about_text():
    """Возвращает текст 'О программе' для GUI"""
    return f"""
{__product__}
Версия {__version__}

{__description__}

Статус: {__status__}
Лицензия: {__license__}
Python: {__python_requires__}

© 2026 {__author__}
"""

# Константы для сборки
BUILD_NAME = "CoreStructure"
BUILD_DISPLAY_NAME = "Core Structure"
