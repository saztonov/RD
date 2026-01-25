"""Генератор Markdown (_document.md) из OCR результатов (оптимизирован для LLM).

ПРИМЕЧАНИЕ: Этот модуль перенесён в rd_core/ocr/md/.
Данный файл обеспечивает обратную совместимость.
"""

# Реэкспорт из нового модуля для обратной совместимости
from .md import (
    generate_md_from_pages,
    generate_md_from_result,
)

__all__ = [
    "generate_md_from_pages",
    "generate_md_from_result",
]
