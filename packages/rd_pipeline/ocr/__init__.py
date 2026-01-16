"""OCR subsystem for rd_pipeline."""

from rd_pipeline.ocr.backends import (
    DatalabOCRBackend,
    DummyOCRBackend,
    OpenRouterBackend,
)
from rd_pipeline.ocr.factory import create_ocr_engine
from rd_pipeline.ocr.ports import OCRBackend
from rd_pipeline.ocr.utils import (
    image_to_base64,
    image_to_pdf_base64,
    pdf_file_to_base64,
)

__all__ = [
    # Ports
    "OCRBackend",
    # Backends
    "DummyOCRBackend",
    "OpenRouterBackend",
    "DatalabOCRBackend",
    # Factory
    "create_ocr_engine",
    # Utils
    "image_to_base64",
    "image_to_pdf_base64",
    "pdf_file_to_base64",
]
