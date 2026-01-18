"""Mixin для CRUD операций с узлами дерева"""
from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional

from apps.rd_desktop.tree_models import (
    NodeStatus,
    NodeType,
    SectionType,
    StageType,
    TreeNode,
)

logger = logging.getLogger(__name__)


class TreeNodesMixin:
    """CRUD операции с узлами дерева"""

    # === Справочники ===

    def get_stage_types(self) -> List[StageType]:
        """Получить типы стадий"""
        resp = self._request("get", "/stage_types?order=sort_order")
        return [
            StageType(
                id=r["id"],
                code=r["code"],
                name=r["name"],
                sort_order=r.get("sort_order", 0),
            )
            for r in resp.json()
        ]

    def get_section_types(self) -> List[SectionType]:
        """Получить типы разделов"""
        resp = self._request("get", "/section_types?order=sort_order")
        return [
            SectionType(
                id=r["id"],
                code=r["code"],
                name=r["name"],
                sort_order=r.get("sort_order", 0),
            )
            for r in resp.json()
        ]

    # === CRUD для узлов ===

    def get_root_nodes(
        self, use_client_filter: bool = True, client_id: Optional[str] = None
    ) -> List[TreeNode]:
        """Получить корневые проекты (без parent_id).

        Если задан фильтр для client_id, возвращает только доступные проекты.
        """
        if use_client_filter:
            root_ids = self.get_client_root_ids(client_id)
            if root_ids is not None:
                if not root_ids:
                    return []
                ids_str = ",".join(f'"{rid}"' for rid in root_ids)
                resp = self._request(
                    "get",
                    f"/tree_nodes?id=in.({ids_str})&parent_id=is.null&order=sort_order,created_at",
                )
                return [TreeNode.from_dict(r) for r in resp.json()]

        resp = self._request(
            "get", "/tree_nodes?parent_id=is.null&order=sort_order,created_at"
        )
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_root_nodes_all(self) -> List[TreeNode]:
        """Получить все корневые проекты (без фильтра по client_id)."""
        return self.get_root_nodes(use_client_filter=False)

    def get_children(self, parent_id: str) -> List[TreeNode]:
        """Получить дочерние узлы (Lazy Loading)"""
        resp = self._request(
            "get", f"/tree_nodes?parent_id=eq.{parent_id}&order=sort_order,created_at"
        )
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_node(self, node_id: str) -> Optional[TreeNode]:
        """Получить узел по ID"""
        resp = self._request("get", f"/tree_nodes?id=eq.{node_id}")
        data = resp.json()
        return TreeNode.from_dict(data[0]) if data else None

    def create_node(
        self,
        node_type,
        name: str,
        parent_id: Optional[str] = None,
        code: Optional[str] = None,
        attributes: Optional[Dict] = None,
    ) -> TreeNode:
        """Создать новый узел"""
        # Конвертируем в строку для API
        if isinstance(node_type, NodeType):
            node_type_str = node_type.value
        else:
            node_type_str = str(node_type)

        node_id = str(uuid.uuid4())
        payload = {
            "id": node_id,
            "parent_id": parent_id,
            "node_type": node_type_str,
            "name": name,
            "code": code,
            "attributes": attributes or {},
        }
        resp = self._request("post", "/tree_nodes", json=payload)
        return TreeNode.from_dict(resp.json()[0])

    def update_node(self, node_id: str, **fields) -> Optional[TreeNode]:
        """Обновить узел"""
        update_data = {}
        if "name" in fields:
            update_data["name"] = fields["name"]
        if "code" in fields:
            update_data["code"] = fields["code"]
        if "status" in fields:
            update_data["status"] = (
                fields["status"].value
                if isinstance(fields["status"], NodeStatus)
                else fields["status"]
            )
        if "attributes" in fields:
            update_data["attributes"] = fields["attributes"]
        if "sort_order" in fields:
            update_data["sort_order"] = fields["sort_order"]
        if "parent_id" in fields:
            update_data["parent_id"] = fields["parent_id"]
        if "version" in fields:
            update_data["version"] = fields["version"]

        if not update_data:
            return self.get_node(node_id)

        resp = self._request("patch", f"/tree_nodes?id=eq.{node_id}", json=update_data)
        data = resp.json()
        return TreeNode.from_dict(data[0]) if data else None

    def delete_node(self, node_id: str) -> bool:
        """Удалить узел (каскадно удалит дочерние)"""
        try:
            self._request("delete", f"/tree_nodes?id=eq.{node_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete node {node_id}: {e}")
            return False

    def move_node(self, node_id: str, new_parent_id: Optional[str]) -> bool:
        """Переместить узел к другому родителю"""
        # Валидация: нельзя переместить в себя или в своих потомков
        if new_parent_id:
            if node_id == new_parent_id:
                return False
            # Проверяем что new_parent не потомок node
            parent = self.get_node(new_parent_id)
            while parent and parent.parent_id:
                if parent.parent_id == node_id:
                    return False
                parent = self.get_node(parent.parent_id)

        return self.update_node(node_id, parent_id=new_parent_id) is not None

    def get_full_tree(self, max_depth: int = 2) -> List[TreeNode]:
        """Получить дерево с вложенностью до max_depth"""
        roots = self.get_root_nodes()

        def load_children(node: TreeNode, depth: int):
            if depth >= max_depth:
                return
            node.children = self.get_children(node.id)
            for child in node.children:
                load_children(child, depth + 1)

        for root in roots:
            load_children(root, 0)

        return roots
