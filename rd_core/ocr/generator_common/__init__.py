"""Общие утилиты для генераторов HTML, Markdown и result.json из OCR результатов."""
from rd_core.ocr.generator_common.block_utils import (
    collect_block_groups,
    get_block_armor_id,
)
from rd_core.ocr.generator_common.html_template import (
    HTML_FOOTER,
    HTML_TEMPLATE,
    get_html_header,
)
from rd_core.ocr.generator_common.image_data import (
    extract_image_ocr_data,
    is_image_ocr_json,
)
from rd_core.ocr.generator_common.linked_blocks import (
    build_linked_blocks_index,
    build_linked_blocks_index_dict,
)
from rd_core.ocr.generator_common.sanitizers import (
    DATALAB_IMG_PATTERN,
    DATALAB_MD_IMG_PATTERN,
    sanitize_html,
    sanitize_markdown,
)
from rd_core.ocr.generator_common.stamp_utils import (
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
