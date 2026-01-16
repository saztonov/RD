"""OCR backends."""

from rd_pipeline.ocr.backends.datalab import DatalabOCRBackend
from rd_pipeline.ocr.backends.dummy import DummyOCRBackend
from rd_pipeline.ocr.backends.openrouter import OpenRouterBackend

__all__ = [
    "DummyOCRBackend",
    "OpenRouterBackend",
    "DatalabOCRBackend",
]
