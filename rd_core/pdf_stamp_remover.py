"""
DEPRECATED: Import from rd_pipeline.pdf instead.

This module is kept for backward compatibility.
"""
import warnings

from rd_pipeline.pdf import (
    PDFStampRemover,
    remove_stamps_from_pdf,
)

__all__ = [
    "PDFStampRemover",
    "remove_stamps_from_pdf",
]


def __getattr__(name):
    warnings.warn(
        "rd_core.pdf_stamp_remover is deprecated. Import from rd_pipeline.pdf instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
