"""
DEPRECATED: Import from rd_pipeline.pdf instead.

This module is kept for backward compatibility.
"""
import warnings

from rd_pipeline.pdf import (
    PDFStatus,
    calculate_pdf_status,
    update_pdf_status_in_db,
)

__all__ = [
    "PDFStatus",
    "calculate_pdf_status",
    "update_pdf_status_in_db",
]


def __getattr__(name):
    warnings.warn(
        "rd_core.pdf_status is deprecated. Import from rd_pipeline.pdf instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
