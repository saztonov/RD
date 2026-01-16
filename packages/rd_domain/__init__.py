"""
rd_domain - Pure domain layer for RD project.

This package contains domain models, identifiers, and annotation schemas
with zero external dependencies (except standard library).

Modules:
    ids: ArmorID - OCR-resistant block identifiers
    models: Block, Document, Page, enums
    annotation: Annotation I/O and migration
    manifest: Two-pass OCR manifest models
    utils: Datetime utilities
"""

from rd_domain.ids import (
    ArmorID,
    decode_armor_code,
    encode_block_id,
    generate_armor_id,
    is_armor_id,
    match_armor_to_uuid,
    migrate_block_id,
    uuid_to_armor_id,
)
from rd_domain.models import (
    Block,
    BlockSource,
    BlockType,
    Document,
    Page,
    ShapeType,
)
from rd_domain.utils import get_moscow_time_str

__all__ = [
    # IDs
    "ArmorID",
    "generate_armor_id",
    "is_armor_id",
    "uuid_to_armor_id",
    "migrate_block_id",
    "encode_block_id",
    "decode_armor_code",
    "match_armor_to_uuid",
    # Models
    "Block",
    "Page",
    "Document",
    "BlockType",
    "BlockSource",
    "ShapeType",
    # Utils
    "get_moscow_time_str",
]

__version__ = "1.0.0"
