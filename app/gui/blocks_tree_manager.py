"""Обратная совместимость: реэкспорт BlocksTreeManager из blocks_tree/."""
from app.gui.blocks_tree import BlocksTreeManager  # noqa: F401

__all__ = ["BlocksTreeManager"]
