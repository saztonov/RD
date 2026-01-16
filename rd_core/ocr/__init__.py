"""
OCR module - backward compatibility shim.

DEPRECATED: Import from rd_pipeline.ocr and rd_pipeline.output instead.
"""

# Re-export from rd_pipeline.ocr
from rd_pipeline.ocr import (
    OCRBackend,
    OpenRouterBackend,
    DatalabOCRBackend,
    DummyOCRBackend,
    create_ocr_engine,
    image_to_base64,
)

# Re-export from rd_pipeline.output
from rd_pipeline.output import (
    generate_html_from_pages,
    generate_md_from_pages,
    generate_md_from_result,
)

# Backward compat alias
image_to_pdf_base64 = image_to_base64

__all__ = [
    "OCRBackend",
    "OpenRouterBackend",
    "DatalabOCRBackend",
    "DummyOCRBackend",
    "image_to_base64",
    "image_to_pdf_base64",
    "generate_html_from_pages",
    "generate_md_from_pages",
    "generate_md_from_result",
    "create_ocr_engine",
]
