"""
Клиент для работы с деревом проектов в Supabase.

Модуль разбит на mixins по функциональности:
- base.py: HTTP инфраструктура и базовый класс
- client_access_mixin.py: доступ клиента к корневым проектам
- nodes_mixin.py: CRUD операции с узлами
- pdf_status_mixin.py: статусы PDF и блокировки
- documents_mixin.py: документы и node_files
- categories_mixin.py: категории изображений
- stats_mixin.py: статистика и materialized path
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.rd_desktop.tree_client.base import TreeClientBase, _get_tree_client
from apps.rd_desktop.tree_client.categories_mixin import TreeCategoriesMixin
from apps.rd_desktop.tree_client.client_access_mixin import TreeClientAccessMixin
from apps.rd_desktop.tree_client.documents_mixin import TreeDocumentsMixin
from apps.rd_desktop.tree_client.nodes_mixin import TreeNodesMixin
from apps.rd_desktop.tree_client.pdf_status_mixin import TreePdfStatusMixin
from apps.rd_desktop.tree_client.stats_mixin import TreeStatsMixin

# Реэкспорт моделей для обратной совместимости
from apps.rd_desktop.tree_models import (
    ALLOWED_CHILDREN,
    FileType,
    NodeFile,
    NodeStatus,
    NodeType,
    SectionType,
    StageType,
    TreeNode,
)


@dataclass
class TreeClient(
    TreeClientBase,
    TreeClientAccessMixin,
    TreeNodesMixin,
    TreePdfStatusMixin,
    TreeDocumentsMixin,
    TreeCategoriesMixin,
    TreeStatsMixin,
):
    """
    Клиент для работы с деревом проектов.

    Составлен из mixins:
    - TreeClientBase: HTTP инфраструктура
    - TreeClientAccessMixin: доступ клиента к корневым проектам
    - TreeNodesMixin: CRUD узлов
    - TreePdfStatusMixin: статусы PDF и блокировки
    - TreeDocumentsMixin: документы и node_files
    - TreeCategoriesMixin: категории изображений
    - TreeStatsMixin: статистика и path операции
    """
    pass


__all__ = [
    # Основной класс
    "TreeClient",
    "_get_tree_client",
    # Модели (реэкспорт для обратной совместимости)
    "NodeType",
    "NodeStatus",
    "FileType",
    "NodeFile",
    "TreeNode",
    "StageType",
    "SectionType",
    "ALLOWED_CHILDREN",
]
