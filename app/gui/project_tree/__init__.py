"""Модуль дерева проектов"""
from app.gui.project_tree.widget import ProjectTreeWidget

# Названия типов узлов для UI
from app.tree_client import NodeType

NODE_TYPE_NAMES = {
    NodeType.PROJECT: "Проект",
    NodeType.STAGE: "Стадия",
    NodeType.SECTION: "Раздел",
    NodeType.TASK_FOLDER: "Папка заданий",
    NodeType.DOCUMENT: "Документ",
}

__all__ = ["ProjectTreeWidget", "NODE_TYPE_NAMES"]
