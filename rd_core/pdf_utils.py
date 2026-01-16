"""
DEPRECATED: Import from rd_pipeline.pdf instead.

This module is kept for backward compatibility.
"""
import warnings

from rd_pipeline.pdf import (
    PDF_PREVIEW_DPI,
    PDF_PREVIEW_ZOOM,
    PDF_RENDER_DPI,
    PDF_RENDER_ZOOM,
    PDFDocument,
    extract_text_for_block,
    extract_text_pdfplumber,
    get_pdf_page_size,
    open_pdf,
    render_page_to_image,
)

__all__ = [
    "open_pdf",
    "render_page_to_image",
    "PDFDocument",
    "extract_text_pdfplumber",
    "extract_text_for_block",
    "get_pdf_page_size",
    "PDF_RENDER_DPI",
    "PDF_RENDER_ZOOM",
    "PDF_PREVIEW_DPI",
    "PDF_PREVIEW_ZOOM",
]


def __getattr__(name):
    warnings.warn(
        "rd_core.pdf_utils is deprecated. Import from rd_pipeline.pdf instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
