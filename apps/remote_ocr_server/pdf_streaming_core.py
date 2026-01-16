"""
DEPRECATED: Import from rd_pipeline.processing.streaming_pdf instead.

This module is a backward compatibility shim that uses server settings.
"""
from __future__ import annotations

import warnings
from typing import Dict, List, Optional, Tuple

from PIL import Image

warnings.warn(
    "apps.remote_ocr_server.pdf_streaming_core is deprecated. "
    "Use rd_pipeline.processing.streaming_pdf instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .settings import settings

# Build ProcessingConfig from server settings
from rd_pipeline.processing.config import ProcessingConfig

_server_config = ProcessingConfig(
    pdf_render_dpi=settings.pdf_render_dpi,
    max_strip_height=settings.max_strip_height,
    crop_png_compress=settings.crop_png_compress,
    max_crop_dimension=settings.max_crop_dimension,
    min_crop_dpi=settings.min_crop_dpi,
    ocr_prep_enabled=settings.ocr_prep_enabled,
    ocr_prep_contrast=settings.ocr_prep_contrast,
    ocr_threads_per_job=settings.ocr_threads_per_job,
)

# Re-export constants with server settings
PDF_RENDER_DPI = settings.pdf_render_dpi
PDF_RENDER_ZOOM = PDF_RENDER_DPI / 72.0
MAX_STRIP_HEIGHT = settings.max_strip_height
MAX_SINGLE_BLOCK_HEIGHT = settings.max_strip_height
MAX_IMAGE_PIXELS = 400_000_000

# Re-export from rd_pipeline.processing.streaming_pdf
from rd_pipeline.processing.streaming_pdf import (
    StreamingPDFProcessor as _StreamingPDFProcessor,
    split_large_crop as _split_large_crop,
    create_block_separator,
    merge_crops_vertically,
    get_page_dimensions_streaming,
    calculate_adaptive_dpi,
    apply_ocr_preprocessing,
    render_block_crop,
    BLOCK_SEPARATOR_HEIGHT,
    BUNDLED_FONT_PATH,
    _apply_polygon_mask_to_crop,
)


class StreamingPDFProcessor(_StreamingPDFProcessor):
    """Server-configured StreamingPDFProcessor."""

    def __init__(self, pdf_path: str, zoom: float = PDF_RENDER_ZOOM, config=None):
        super().__init__(pdf_path, zoom=zoom, config=config or _server_config)


def split_large_crop(
    crop: Image.Image, max_height: int = MAX_SINGLE_BLOCK_HEIGHT, overlap: int = 100
) -> List[Image.Image]:
    """Server-configured split_large_crop."""
    return _split_large_crop(crop, max_height=max_height, overlap=overlap, config=_server_config)


__all__ = [
    "StreamingPDFProcessor",
    "split_large_crop",
    "create_block_separator",
    "merge_crops_vertically",
    "get_page_dimensions_streaming",
    "calculate_adaptive_dpi",
    "apply_ocr_preprocessing",
    "render_block_crop",
    "BLOCK_SEPARATOR_HEIGHT",
    "BUNDLED_FONT_PATH",
    "_apply_polygon_mask_to_crop",
    "PDF_RENDER_DPI",
    "PDF_RENDER_ZOOM",
    "MAX_STRIP_HEIGHT",
    "MAX_SINGLE_BLOCK_HEIGHT",
    "MAX_IMAGE_PIXELS",
]
