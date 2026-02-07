"""
Модель данных приложения.
Содержит классы для представления страниц PDF и блоков разметки.
"""
from rd_core.models.armor_id import (
    ArmorID,
    encode_block_id,
    generate_armor_id,
    get_moscow_time_str,
    is_armor_id,
    match_armor_to_uuid,
    migrate_block_id,
    uuid_to_armor_id,
)
from rd_core.models.block import Block
from rd_core.models.document import Document, Page
from rd_core.models.enums import BlockSource, BlockType, ShapeType

__all__ = [
    # Основные классы
    "Block",
    "Page",
    "Document",
    # Enums
    "BlockType",
    "BlockSource",
    "ShapeType",
    # ArmorID
    "ArmorID",
    "generate_armor_id",
    "is_armor_id",
    "uuid_to_armor_id",
    "migrate_block_id",
    "encode_block_id",
    "match_armor_to_uuid",
    "get_moscow_time_str",
]
