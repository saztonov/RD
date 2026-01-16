"""Enumerations for data models."""

from enum import Enum


class BlockType(Enum):
    """Block types (2 types: text and image)."""

    TEXT = "text"
    IMAGE = "image"


class BlockSource(Enum):
    """Block creation source."""

    USER = "user"  # Created by user manually
    AUTO = "auto"  # Created by automatic segmentation


class ShapeType(Enum):
    """Block shape type."""

    RECTANGLE = "rectangle"
    POLYGON = "polygon"
