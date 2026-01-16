"""
Generator common utilities - backward compatibility shim.

DEPRECATED: Import from rd_pipeline.common instead.
"""

# Re-export everything from rd_pipeline.common
from rd_pipeline.common import (
    # html_template
    HTML_TEMPLATE,
    HTML_FOOTER,
    get_html_header,
    # sanitizers
    DATALAB_IMG_PATTERN,
    DATALAB_MD_IMG_PATTERN,
    sanitize_html,
    sanitize_markdown,
    # image_data
    extract_image_ocr_data,
    is_image_ocr_json,
    # stamp_utils
    INHERITABLE_STAMP_FIELDS,
    parse_stamp_json,
    find_page_stamp,
    collect_inheritable_stamp_data,
    format_stamp_parts,
    find_page_stamp_dict,
    collect_inheritable_stamp_data_dict,
    propagate_stamp_data,
    # linked_blocks
    build_linked_blocks_index,
    build_linked_blocks_index_dict,
    # block_utils
    get_block_armor_id,
    collect_block_groups,
)

__all__ = [
    # html_template
    "HTML_TEMPLATE",
    "HTML_FOOTER",
    "get_html_header",
    # sanitizers
    "DATALAB_IMG_PATTERN",
    "DATALAB_MD_IMG_PATTERN",
    "sanitize_html",
    "sanitize_markdown",
    # image_data
    "extract_image_ocr_data",
    "is_image_ocr_json",
    # stamp_utils
    "INHERITABLE_STAMP_FIELDS",
    "parse_stamp_json",
    "find_page_stamp",
    "collect_inheritable_stamp_data",
    "format_stamp_parts",
    "find_page_stamp_dict",
    "collect_inheritable_stamp_data_dict",
    "propagate_stamp_data",
    # linked_blocks
    "build_linked_blocks_index",
    "build_linked_blocks_index_dict",
    # block_utils
    "get_block_armor_id",
    "collect_block_groups",
]
