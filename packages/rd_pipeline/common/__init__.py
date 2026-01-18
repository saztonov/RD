"""Common utilities for output generators."""

from rd_pipeline.common.block_utils import (
    collect_block_groups,
    get_block_armor_id,
)
from rd_pipeline.common.image_data import (
    extract_image_ocr_data,
    is_image_ocr_json,
)
from rd_pipeline.common.linked_blocks import (
    build_linked_blocks_index,
    build_linked_blocks_index_dict,
)
from rd_pipeline.common.sanitizers import (
    DATALAB_MD_IMG_PATTERN,
    html_to_markdown,
    sanitize_markdown,
)
from rd_pipeline.common.stamp_utils import (
    INHERITABLE_STAMP_FIELDS,
    collect_inheritable_stamp_data,
    collect_inheritable_stamp_data_dict,
    find_page_stamp,
    find_page_stamp_dict,
    format_stamp_parts,
    parse_stamp_json,
    propagate_stamp_data,
)

__all__ = [
    # sanitizers
    "DATALAB_MD_IMG_PATTERN",
    "html_to_markdown",
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
