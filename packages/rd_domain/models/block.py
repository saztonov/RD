"""
Block model for PDF page annotation.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from rd_domain.ids import generate_armor_id, migrate_block_id
from rd_domain.models.enums import BlockSource, BlockType, ShapeType
from rd_domain.utils import get_moscow_time_str


@dataclass
class Block:
    """
    Annotation block on PDF page.

    Attributes:
        id: unique block identifier (ArmorID format)
        page_index: page index (starting from 0)
        coords_px: pixel coordinates (x1, y1, x2, y2) on rendered image
        coords_norm: normalized coordinates (0..1) relative to width/height
        block_type: block type (TEXT/IMAGE)
        source: creation source (USER/AUTO)
        shape_type: shape type (RECTANGLE/POLYGON)
        polygon_points: polygon vertex coordinates [(x1,y1), (x2,y2), ...] for POLYGON
        image_file: path to saved block crop
        ocr_text: OCR recognition result
        prompt: OCR prompt (dict with keys system/user)
        hint: user hint for IMAGE block (content description)
        pdfplumber_text: raw text extracted by pdfplumber for block
        linked_block_id: linked block ID (for IMAGE+TEXT)
        group_id: block group ID (None = common group)
        group_name: group name (displayed to user)
        category_id: image category ID (for IMAGE blocks)
        category_code: image category code (for serialization)
        created_at: block creation date and time (ISO format)
    """

    id: str
    page_index: int
    coords_px: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    coords_norm: Tuple[float, float, float, float]  # (x1, y1, x2, y2) in range 0..1
    block_type: BlockType
    source: BlockSource
    shape_type: ShapeType = ShapeType.RECTANGLE
    polygon_points: Optional[List[Tuple[int, int]]] = None  # For polygons
    image_file: Optional[str] = None
    ocr_text: Optional[str] = None
    prompt: Optional[dict] = None  # {"system": "...", "user": "..."}
    hint: Optional[str] = None  # User hint for IMAGE block
    pdfplumber_text: Optional[str] = None  # Raw pdfplumber text
    linked_block_id: Optional[str] = None  # Linked block ID
    group_id: Optional[str] = None  # Block group ID
    group_name: Optional[str] = None  # Group name
    category_id: Optional[str] = None  # Image category ID
    category_code: Optional[str] = None  # Image category code (for serialization)
    created_at: Optional[str] = None  # Creation date (ISO format)

    @staticmethod
    def generate_id() -> str:
        """Generate unique block ID in format XXXX-XXXX-XXX."""
        return generate_armor_id()

    @staticmethod
    def px_to_norm(
        coords_px: Tuple[int, int, int, int], page_width: int, page_height: int
    ) -> Tuple[float, float, float, float]:
        """
        Convert pixel coordinates to normalized (0..1).

        Args:
            coords_px: pixel coordinates (x1, y1, x2, y2)
            page_width: page width in pixels
            page_height: page height in pixels

        Returns:
            Normalized coordinates (x1, y1, x2, y2)
        """
        x1, y1, x2, y2 = coords_px
        return (x1 / page_width, y1 / page_height, x2 / page_width, y2 / page_height)

    @staticmethod
    def norm_to_px(
        coords_norm: Tuple[float, float, float, float],
        page_width: int,
        page_height: int,
    ) -> Tuple[int, int, int, int]:
        """
        Convert normalized coordinates (0..1) to pixels.

        Args:
            coords_norm: normalized coordinates (x1, y1, x2, y2)
            page_width: page width in pixels
            page_height: page height in pixels

        Returns:
            Pixel coordinates (x1, y1, x2, y2)
        """
        x1, y1, x2, y2 = coords_norm
        return (
            int(x1 * page_width),
            int(y1 * page_height),
            int(x2 * page_width),
            int(y2 * page_height),
        )

    @classmethod
    def create(
        cls,
        page_index: int,
        coords_px: Tuple[int, int, int, int],
        page_width: int,
        page_height: int,
        block_type: BlockType,
        source: BlockSource,
        shape_type: ShapeType = ShapeType.RECTANGLE,
        polygon_points: Optional[List[Tuple[int, int]]] = None,
        image_file: Optional[str] = None,
        ocr_text: Optional[str] = None,
        block_id: Optional[str] = None,
        prompt: Optional[dict] = None,
        hint: Optional[str] = None,
        pdfplumber_text: Optional[str] = None,
        linked_block_id: Optional[str] = None,
    ) -> "Block":
        """
        Create block with automatic normalized coordinates calculation.

        Args:
            page_index: page index
            coords_px: pixel coordinates (x1, y1, x2, y2)
            page_width: page width in pixels
            page_height: page height in pixels
            block_type: block type
            source: creation source
            shape_type: shape type (rectangle/polygon)
            polygon_points: polygon vertices
            image_file: crop path
            ocr_text: OCR result
            block_id: block ID (if None, generated automatically)
            prompt: OCR prompt
            hint: user hint for IMAGE block
            pdfplumber_text: raw pdfplumber text
            linked_block_id: linked block ID

        Returns:
            New Block instance
        """
        coords_norm = cls.px_to_norm(coords_px, page_width, page_height)

        return cls(
            id=block_id or cls.generate_id(),
            page_index=page_index,
            coords_px=coords_px,
            coords_norm=coords_norm,
            block_type=block_type,
            source=source,
            shape_type=shape_type,
            polygon_points=polygon_points,
            image_file=image_file,
            ocr_text=ocr_text,
            prompt=prompt,
            hint=hint,
            pdfplumber_text=pdfplumber_text,
            linked_block_id=linked_block_id,
            created_at=get_moscow_time_str(),
        )

    def get_width_height_px(self) -> Tuple[int, int]:
        """Get block width and height in pixels."""
        x1, y1, x2, y2 = self.coords_px
        return (x2 - x1, y2 - y1)

    def get_width_height_norm(self) -> Tuple[float, float]:
        """Get block width and height in normalized coordinates."""
        x1, y1, x2, y2 = self.coords_norm
        return (x2 - x1, y2 - y1)

    def update_coords_px(
        self,
        new_coords_px: Tuple[int, int, int, int],
        page_width: int,
        page_height: int,
    ):
        """
        Update pixel coordinates and recalculate normalized.

        Args:
            new_coords_px: new pixel coordinates
            page_width: page width
            page_height: page height
        """
        self.coords_px = new_coords_px
        self.coords_norm = self.px_to_norm(new_coords_px, page_width, page_height)

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON."""
        result = {
            "id": self.id,
            "page_index": self.page_index,
            "coords_px": list(self.coords_px),
            "coords_norm": list(self.coords_norm),
            "block_type": self.block_type.value,
            "source": self.source.value,
            "shape_type": self.shape_type.value,
            "image_file": self.image_file,
            "ocr_text": self.ocr_text,
        }
        if self.polygon_points:
            result["polygon_points"] = [list(p) for p in self.polygon_points]
        if self.prompt:
            result["prompt"] = self.prompt
        if self.hint:
            result["hint"] = self.hint
        if self.pdfplumber_text:
            result["pdfplumber_text"] = self.pdfplumber_text
        if self.linked_block_id:
            result["linked_block_id"] = self.linked_block_id
        if self.group_id:
            result["group_id"] = self.group_id
        if self.group_name:
            result["group_name"] = self.group_name
        if self.category_id:
            result["category_id"] = self.category_id
        if self.category_code:
            result["category_code"] = self.category_code
        if self.created_at:
            result["created_at"] = self.created_at
        return result

    @classmethod
    def from_dict(cls, data: dict, migrate_ids: bool = True) -> tuple["Block", bool]:
        """
        Deserialize from dictionary.

        Args:
            data: dictionary with block data
            migrate_ids: migrate UUID to armor ID format

        Returns:
            (Block, was_migrated) - block and migration flag
        """
        # Safe block_type extraction with fallback to TEXT
        # TABLE converts to TEXT for backward compatibility
        raw_type = data["block_type"]
        if raw_type == "table":
            block_type = BlockType.TEXT
        else:
            try:
                block_type = BlockType(raw_type)
            except ValueError:
                block_type = BlockType.TEXT

        # Safe shape_type extraction with fallback to RECTANGLE
        try:
            shape_type = ShapeType(data.get("shape_type", "rectangle"))
        except ValueError:
            shape_type = ShapeType.RECTANGLE

        # Get polygon_points if present
        polygon_points = None
        if "polygon_points" in data and data["polygon_points"]:
            polygon_points = [tuple(p) for p in data["polygon_points"]]

        # ID migration
        was_migrated = False
        block_id = data["id"]
        linked_block_id = data.get("linked_block_id")
        group_id = data.get("group_id")

        if migrate_ids:
            block_id, m1 = migrate_block_id(block_id)
            was_migrated = m1

            if linked_block_id:
                linked_block_id, m2 = migrate_block_id(linked_block_id)
                was_migrated = was_migrated or m2

            if group_id:
                group_id, m3 = migrate_block_id(group_id)
                was_migrated = was_migrated or m3

        block = cls(
            id=block_id,
            page_index=data["page_index"],
            coords_px=tuple(data["coords_px"]),
            coords_norm=tuple(data["coords_norm"]),
            block_type=block_type,
            source=BlockSource(data["source"]),
            shape_type=shape_type,
            polygon_points=polygon_points,
            image_file=data.get("image_file"),
            ocr_text=data.get("ocr_text"),
            prompt=data.get("prompt"),
            hint=data.get("hint"),
            pdfplumber_text=data.get("pdfplumber_text"),
            linked_block_id=linked_block_id,
            group_id=group_id,
            group_name=data.get("group_name"),
            category_id=data.get("category_id"),
            category_code=data.get("category_code"),
            created_at=data.get("created_at") or get_moscow_time_str(),
        )
        return block, was_migrated
