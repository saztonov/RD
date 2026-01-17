"""Output generators for OCR results - HTML and Markdown."""

from rd_pipeline.output.html_generator import generate_html_from_pages
from rd_pipeline.output.md_generator import (
    generate_md_from_pages,
    generate_md_from_result,
)

__all__ = [
    "generate_html_from_pages",
    "generate_md_from_pages",
    "generate_md_from_result",
]
