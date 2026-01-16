"""PDF utilities for rd_pipeline."""

from rd_pipeline.pdf.utils import (
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
from rd_pipeline.pdf.status import (
    PDFStatus,
    calculate_pdf_status,
    update_pdf_status_in_db,
)
from rd_pipeline.pdf.stamp_remover import (
    PDFStampRemover,
    remove_stamps_from_pdf,
)

__all__ = [
    # utils
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
    # status
    "PDFStatus",
    "calculate_pdf_status",
    "update_pdf_status_in_db",
    # stamp_remover
    "PDFStampRemover",
    "remove_stamps_from_pdf",
]
