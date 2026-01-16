"""ArmorID module - OCR-resistant block identifiers."""

from .armor_id import (
    ArmorID,
    decode_armor_code,
    encode_block_id,
    generate_armor_id,
    is_armor_id,
    match_armor_to_uuid,
    migrate_block_id,
    uuid_to_armor_id,
)

__all__ = [
    "ArmorID",
    "generate_armor_id",
    "is_armor_id",
    "uuid_to_armor_id",
    "migrate_block_id",
    "encode_block_id",
    "decode_armor_code",
    "match_armor_to_uuid",
]
