"""
Configuration dataclass for processing module.

This provides defaults that can be overridden by server-specific settings.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessingConfig:
    """Configuration for OCR processing pipeline."""

    # PDF rendering
    pdf_render_dpi: int = 150
    max_image_pixels: int = 400_000_000

    # Strip/crop settings
    max_strip_height: int = 9000
    max_single_block_height: int = 9000
    crop_png_compress: int = 6

    # Clip rendering (for large sheets A0/A1)
    max_crop_dimension: int = 4000
    min_crop_dpi: int = 150

    # OCR preprocessing
    ocr_prep_enabled: bool = False
    ocr_prep_contrast: float = 1.3

    # Threading
    ocr_threads_per_job: int = 2

    # Block separator
    block_separator_height: int = 120

    @property
    def pdf_render_zoom(self) -> float:
        """Calculate zoom factor from DPI."""
        return self.pdf_render_dpi / 72.0


# Default configuration instance
default_config = ProcessingConfig()
