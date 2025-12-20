"""
OCR обработка через API движки - модуль обратной совместимости
Все компоненты перенесены в rd_core/ocr/
"""

# Реэкспорт для обратной совместимости
from rd_core.ocr import (
    OCRBackend,
    OpenRouterBackend,
    DatalabOCRBackend,
    DummyOCRBackend,
    image_to_base64,
    image_to_pdf_base64,
    generate_structured_markdown,
    create_ocr_engine,
)

__all__ = [
    "OCRBackend",
    "OpenRouterBackend",
    "DatalabOCRBackend",
    "DummyOCRBackend",
    "image_to_base64",
    "image_to_pdf_base64",
    "generate_structured_markdown",
    "create_ocr_engine",
]
