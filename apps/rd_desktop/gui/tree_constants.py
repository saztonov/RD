"""Константы и утилиты для дерева проектов"""
from apps.rd_desktop.tree_client import NodeStatus, NodeType, TreeNode

NODE_ICONS = {
    # Новые типы v2
    NodeType.FOLDER: "📁",
    NodeType.DOCUMENT: "📄",
    # Legacy aliases (для обратной совместимости с данными в БД)
    "project": "📁",
    "stage": "🏗",
    "section": "📚",
    "task_folder": "📂",
    "document": "📄",
    "folder": "📁",
}

STATUS_COLORS = {
    NodeStatus.ACTIVE: "#e0e0e0",
    NodeStatus.COMPLETED: "#4caf50",
    NodeStatus.ARCHIVED: "#9e9e9e",
}


def get_node_icon(node: TreeNode) -> str:
    """Получить иконку для узла (учитывает legacy_node_type)."""
    # Сначала проверяем legacy_node_type в attributes
    legacy_type = node.legacy_node_type
    if legacy_type and legacy_type in NODE_ICONS:
        return NODE_ICONS[legacy_type]

    # Используем node_type
    if node.node_type in NODE_ICONS:
        return NODE_ICONS[node.node_type]

    # Fallback
    return "📁" if node.is_folder else "📄"
