"""
Document and Page models for PDF (legacy, for GUI compatibility).
"""

from dataclasses import dataclass, field
from typing import List

from rd_domain.models.block import Block


@dataclass
class Page:
    """
    PDF page with annotation blocks (legacy, for GUI compatibility).

    Attributes:
        page_number: page number (starting from 0)
        width: page width in pixels (after rendering)
        height: page height in pixels
        blocks: list of annotation blocks on this page
    """

    page_number: int
    width: int
    height: int
    blocks: List[Block] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON."""
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: dict, migrate_ids: bool = True) -> tuple["Page", bool]:
        """
        Deserialize from dictionary.

        Returns:
            (Page, was_migrated)
        """
        # Support page_index from new model
        page_num = data.get("page_number")
        if page_num is None:
            page_num = data.get("page_index", 0)

        blocks = []
        was_migrated = False
        for b in data.get("blocks", []):
            block, migrated = Block.from_dict(b, migrate_ids)
            blocks.append(block)
            was_migrated = was_migrated or migrated

        return (
            cls(
                page_number=page_num,
                width=data["width"],
                height=data["height"],
                blocks=blocks,
            ),
            was_migrated,
        )


@dataclass
class Document:
    """
    PDF document with annotations (legacy, for compatibility).

    Attributes:
        pdf_path: path to PDF file
        pages: list of pages with annotations
    """

    pdf_path: str
    pages: List[Page] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON."""
        return {
            "pdf_path": self.pdf_path,
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict, migrate_ids: bool = True) -> tuple["Document", bool]:
        """
        Deserialize from dictionary with old format support.

        Returns:
            (Document, was_migrated) - document and ID migration flag
        """
        raw_pages = []
        was_migrated = False
        for p in data.get("pages", []):
            page, migrated = Page.from_dict(p, migrate_ids)
            raw_pages.append(page)
            was_migrated = was_migrated or migrated

        # Determine if this is old format (page_number != array index)
        is_old_format = False
        if raw_pages:
            # Check: first page doesn't start from 0 or there are gaps
            for idx, page in enumerate(raw_pages):
                if page.page_number != idx:
                    is_old_format = True
                    break

        if is_old_format and raw_pages:
            # Old format: create sparse array by page_number
            max_page = max(p.page_number for p in raw_pages)
            # Collect pages in dict by page_number
            pages_by_num = {p.page_number: p for p in raw_pages}

            # Create full array of pages
            pages = []
            for i in range(max_page + 1):
                if i in pages_by_num:
                    pages.append(pages_by_num[i])
                else:
                    # Take dimensions from nearest page
                    ref = raw_pages[0]
                    pages.append(
                        Page(
                            page_number=i, width=ref.width, height=ref.height, blocks=[]
                        )
                    )
        else:
            pages = raw_pages

        return cls(pdf_path=data["pdf_path"], pages=pages), was_migrated
