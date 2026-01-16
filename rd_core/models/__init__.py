"""
Модель данных приложения.
Re-exports from rd_domain for backward compatibility.

DEPRECATED: Import directly from rd_domain.models instead.
"""
import warnings

# Re-export everything from rd_domain
from rd_domain.models import Block, Document, Page
from rd_domain.models import BlockSource, BlockType, ShapeType
from rd_domain.ids import (
    generate_armor_id,
    is_armor_id,
    migrate_block_id,
)
from rd_domain.utils import get_moscow_time_str

# Backward compat alias
uuid_to_armor_id = generate_armor_id

__all__ = [
    # Основные классы
    "Block",
    "Page",
    "Document",
    # Enums
    "BlockType",
    "BlockSource",
    "ShapeType",
    # ArmorID функции
    "generate_armor_id",
    "is_armor_id",
    "uuid_to_armor_id",
    "migrate_block_id",
    "get_moscow_time_str",
]

def __getattr__(name):
    warnings.warn(
        f"rd_core.models is deprecated. Import from rd_domain.models instead.",
        DeprecationWarning,
        stacklevel=2
    )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
