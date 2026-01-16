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
    create_block_separator,
    merge_crops_vertically,
    get_page_dimensions_streaming,
    calculate_adaptive_dpi,
    apply_ocr_preprocessing,
    render_block_crop,
    BLOCK_SEPARATOR_HEIGHT,
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
from rd_pipeline.processing.merge import (
    merge_ocr_results,
    regenerate_html_from_result,
    regenerate_md_from_result,
    HTMLSegmentParser,
    DefaultHTMLSegmentParser,
)

__all__ = [
    # Config
    "ProcessingConfig",
    # Streaming PDF
    "StreamingPDFProcessor",
    "split_large_crop",
    "create_block_separator",
    "merge_crops_vertically",
    "get_page_dimensions_streaming",
    "calculate_adaptive_dpi",
    "apply_ocr_preprocessing",
    "render_block_crop",
    "BLOCK_SEPARATOR_HEIGHT",
    # Two-pass
    "pass1_prepare_crops",
    "pass2_ocr_from_manifest",
    "cleanup_manifest_files",
    "PromptBuilder",
    "TextExtractor",
    "DefaultPromptBuilder",
    "DefaultTextExtractor",
    # Merge
    "merge_ocr_results",
    "regenerate_html_from_result",
    "regenerate_md_from_result",
    "HTMLSegmentParser",
    "DefaultHTMLSegmentParser",
]
