"""
rd_pipeline.processing - Two-pass OCR processing algorithms.

This module contains the core OCR processing logic:
- StreamingPDFProcessor for memory-efficient PDF handling
- Two-pass OCR algorithm (PASS1: crop preparation, PASS2: OCR from disk)
- OCR result merging utilities
"""

from rd_pipeline.processing.config import ProcessingConfig
from rd_pipeline.processing.streaming_pdf import (
    StreamingPDFProcessor,
    split_large_crop,
    get_page_dimensions_streaming,
    calculate_adaptive_dpi,
    apply_ocr_preprocessing,
    render_block_crop,
)
from rd_pipeline.processing.two_pass import (
    pass1_prepare_crops,
    pass2_ocr_from_manifest,
    cleanup_manifest_files,
    PromptBuilder,
    TextExtractor,
    DefaultPromptBuilder,
    DefaultTextExtractor,
)
from rd_pipeline.processing.image_preprocessing import (
    PreprocessMode,
    get_preprocess_mode_for_block,
    preprocess_crop,
    preprocess_for_ocr,
)

__all__ = [
    # Config
    "ProcessingConfig",
    # Streaming PDF
    "StreamingPDFProcessor",
    "split_large_crop",
    "get_page_dimensions_streaming",
    "calculate_adaptive_dpi",
    "apply_ocr_preprocessing",
    "render_block_crop",
    # Two-pass
    "pass1_prepare_crops",
    "pass2_ocr_from_manifest",
    "cleanup_manifest_files",
    "PromptBuilder",
    "TextExtractor",
    "DefaultPromptBuilder",
    "DefaultTextExtractor",
    # Image preprocessing
    "PreprocessMode",
    "get_preprocess_mode_for_block",
    "preprocess_crop",
    "preprocess_for_ocr",
]
