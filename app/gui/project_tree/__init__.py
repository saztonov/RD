"""Модуль дерева проектов"""
from app.gui.project_tree.initial_load_worker import InitialLoadWorker
from app.gui.project_tree.widget import ProjectTreeWidget

# Названия типов узлов для UI
from app.tree_client import NodeType

NODE_TYPE_NAMES = {
    # Новые типы v2
    NodeType.FOLDER: "Папка",
    NodeType.DOCUMENT: "Документ",
    # Legacy (для совместимости со старыми данными)
    "project": "Проект",
    "stage": "Стадия",
    "section": "Раздел",
    "task_folder": "Папка заданий",
    "document": "Документ",
    "folder": "Папка",
}


def get_node_type_name(node_type) -> str:
    """Получить отображаемое имя типа узла."""
    if node_type in NODE_TYPE_NAMES:
        return NODE_TYPE_NAMES[node_type]
    if hasattr(node_type, "value") and node_type.value in NODE_TYPE_NAMES:
        return NODE_TYPE_NAMES[node_type.value]
    return str(node_type)

__all__ = ["InitialLoadWorker", "ProjectTreeWidget", "NODE_TYPE_NAMES", "get_node_type_name"]
