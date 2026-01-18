"""
rd_pipeline - Business logic layer for RD project.

This package contains OCR backends, PDF processing, output generators,
and common utilities. Depends only on rd_domain.

Modules:
    ocr: OCR backends and factory (OpenRouter, Datalab, Dummy)
    common: Shared utilities (sanitizers, stamps, linked blocks)
    pdf: PDF processing (ports and implementations)
    processing: Two-pass OCR processing algorithms
    output: Markdown generators
"""

# OCR
from rd_pipeline.ocr import (
    OCRBackend,
    DummyOCRBackend,
    OpenRouterBackend,
    DatalabOCRBackend,
    create_ocr_engine,
    image_to_base64,
    image_to_pdf_base64,
    pdf_file_to_base64,
)

# Common utilities
from rd_pipeline.common import (
    DATALAB_MD_IMG_PATTERN,
    sanitize_markdown,
    extract_image_ocr_data,
    is_image_ocr_json,
    INHERITABLE_STAMP_FIELDS,
    parse_stamp_json,
    find_page_stamp,
    collect_inheritable_stamp_data,
    format_stamp_parts,
    find_page_stamp_dict,
    collect_inheritable_stamp_data_dict,
    propagate_stamp_data,
    build_linked_blocks_index,
    build_linked_blocks_index_dict,
    get_block_armor_id,
    collect_block_groups,
)

__all__ = [
    # OCR
    "OCRBackend",
    "DummyOCRBackend",
    "OpenRouterBackend",
    "DatalabOCRBackend",
    "create_ocr_engine",
    "image_to_base64",
    "image_to_pdf_base64",
    "pdf_file_to_base64",
    # Common - sanitizers
    "DATALAB_MD_IMG_PATTERN",
    "sanitize_markdown",
    # Common - image data
    "extract_image_ocr_data",
    "is_image_ocr_json",
    # Common - stamps
    "INHERITABLE_STAMP_FIELDS",
    "parse_stamp_json",
    "find_page_stamp",
    "collect_inheritable_stamp_data",
    "format_stamp_parts",
    "find_page_stamp_dict",
    "collect_inheritable_stamp_data_dict",
    "propagate_stamp_data",
    # Common - linked blocks
    "build_linked_blocks_index",
    "build_linked_blocks_index_dict",
    # Common - block utils
    "get_block_armor_id",
    "collect_block_groups",
]

__version__ = "1.0.0"
