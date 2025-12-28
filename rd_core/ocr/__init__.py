"""OCR модуль с поддержкой различных backends"""

from rd_core.ocr.base import OCRBackend
from rd_core.ocr.openrouter import OpenRouterBackend
from rd_core.ocr.datalab import DatalabOCRBackend
from rd_core.ocr.dummy import DummyOCRBackend
from rd_core.ocr.utils import image_to_base64, image_to_pdf_base64
from rd_core.ocr.json_generator import generate_structured_json, generate_grouped_result_json, generate_html_from_ocr
from rd_core.ocr.factory import create_ocr_engine

__all__ = [
    "OCRBackend",
    "OpenRouterBackend", 
    "DatalabOCRBackend",
    "DummyOCRBackend",
    "image_to_base64",
    "image_to_pdf_base64",
    "generate_structured_json",
    "generate_grouped_result_json",
    "generate_html_from_ocr",
    "create_ocr_engine",
]



