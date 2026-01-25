"""Модуль генерации Markdown из OCR результатов."""

from .generator import generate_md_from_pages, generate_md_from_result
from .formatter import format_stamp_md, format_image_ocr_md, process_ocr_content
from .html_converter import html_to_markdown
from .table_converter import table_to_markdown
from .link_collector import (
    collect_image_text_links_from_pages,
    collect_image_text_links_from_result,
    get_text_block_content,
)

__all__ = [
    "generate_md_from_pages",
    "generate_md_from_result",
    "format_stamp_md",
    "format_image_ocr_md",
    "process_ocr_content",
    "html_to_markdown",
    "table_to_markdown",
    "collect_image_text_links_from_pages",
    "collect_image_text_links_from_result",
    "get_text_block_content",
]
