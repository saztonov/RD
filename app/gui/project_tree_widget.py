"""
Виджет дерева проектов с поддержкой Supabase.

DEPRECATED: Этот модуль перемещён в app.gui.project_tree.
Этот файл сохранён для обратной совместимости.
"""
# Реэкспорт из нового модуля
from app.gui.project_tree import NODE_TYPE_NAMES, ProjectTreeWidget

__all__ = ["ProjectTreeWidget", "NODE_TYPE_NAMES"]
