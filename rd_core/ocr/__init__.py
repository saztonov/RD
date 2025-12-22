"""OCR модуль с поддержкой различных backends"""

from rd_core.ocr.base import OCRBackend
from rd_core.ocr.openrouter import OpenRouterBackend
from rd_core.ocr.datalab import DatalabOCRBackend
from rd_core.ocr.dummy import DummyOCRBackend
from rd_core.ocr.utils import image_to_base64, image_to_pdf_base64
from rd_core.ocr.markdown_generator import generate_structured_markdown
from rd_core.ocr.factory import create_ocr_engine

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



