"""Mixin для статистики и операций с materialized path"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from apps.rd_desktop.tree_models import TreeNode

logger = logging.getLogger(__name__)


class TreeStatsMixin:
    """Статистика и операции с materialized path"""

    def get_descendants(self, node_id: str) -> List[TreeNode]:
        """
        Получить всех потомков узла (используя materialized path).
        Быстрее чем рекурсивные запросы для больших деревьев.
        """
        node = self.get_node(node_id)
        if not node or not node.path:
            return []

        # Ищем все узлы чей path начинается с path узла + "."
        resp = self._request(
            "get",
            f"/tree_nodes?path=like.{node.path}.%&order=depth,sort_order",
        )
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_ancestors(self, node_id: str) -> List[TreeNode]:
        """
        Получить всех предков узла (от корня к узлу).
        Использует materialized path для эффективного запроса.
        """
        node = self.get_node(node_id)
        if not node or not node.path:
            return []

        # Парсим path и получаем ID предков
        path_parts = node.path.split(".")
        if len(path_parts) <= 1:
            return []  # Корневой узел, нет предков

        ancestor_ids = path_parts[:-1]  # Все кроме последнего (сам узел)

        # Запрашиваем одним батчем
        ids_str = ",".join(f'"{aid}"' for aid in ancestor_ids)
        resp = self._request("get", f"/tree_nodes?id=in.({ids_str})&order=depth")
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_subtree_stats(self, node_id: str) -> Dict[str, int]:
        """
        Получить статистику поддерева (используя денормализованные счётчики).
        Возвращает: folders_count, documents_count, files_count
        """
        node = self.get_node(node_id)
        if not node:
            return {"folders_count": 0, "documents_count": 0, "files_count": 0}

        # Используем path для подсчёта
        resp = self._request(
            "get",
            f"/tree_nodes?path=like.{node.path}%&select=node_type,files_count",
        )
        data = resp.json()

        folders = sum(1 for r in data if r["node_type"] == "folder")
        documents = sum(1 for r in data if r["node_type"] == "document")
        files = sum(r.get("files_count", 0) for r in data)

        return {
            "folders_count": folders,
            "documents_count": documents,
            "files_count": files,
        }

    def move_node_v2(self, node_id: str, new_parent_id: Optional[str]) -> bool:
        """
        Переместить узел (использует функцию БД move_tree_node для атомарного обновления path).
        """
        try:
            resp = self._request(
                "post",
                "/rpc/move_tree_node",
                json={"p_node_id": node_id, "p_new_parent_id": new_parent_id},
            )
            return resp.json() is True
        except Exception as e:
            logger.error(f"Failed to move node {node_id}: {e}")
            # Fallback на старый метод
            return self.move_node(node_id, new_parent_id)

    def get_tree_stats(
        self, use_client_filter: bool = True, client_id: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Получить общую статистику дерева для текущего клиента.
        Возвращает: pdf_count, md_count, folders_with_pdf
        """
        try:
            root_ids = None
            if use_client_filter:
                root_ids = self.get_client_root_ids(client_id)
                if root_ids is not None and not root_ids:
                    return {"pdf_count": 0, "md_count": 0, "folders_with_pdf": 0}

            # Получаем все узлы
            resp = self._request(
                "get",
                "/tree_nodes?select=id,node_type,parent_id,attributes,path&limit=10000",
            )
            nodes = resp.json()

            # Фильтруем по доступным корневым узлам (если задано)
            if root_ids:
                root_set = set(root_ids)
                filtered = []
                for node in nodes:
                    path = node.get("path") or ""
                    root_id = path.split(".", 1)[0] if path else node.get("id")
                    if root_id in root_set:
                        filtered.append(node)
                nodes = filtered

            logger.info(f"get_tree_stats: total nodes from DB = {len(nodes)}")

            pdf_count = 0
            md_count = 0
            parent_ids_with_pdf = set()
            doc_count = 0

            for node in nodes:
                if node.get("node_type") == "document":
                    doc_count += 1
                    attrs = node.get("attributes") or {}
                    r2_key = attrs.get("r2_key", "")

                    # Считаем PDF
                    if r2_key.lower().endswith(".pdf"):
                        pdf_count += 1
                        # Запоминаем parent_id для подсчёта папок
                        parent_id = node.get("parent_id")
                        if parent_id:
                            parent_ids_with_pdf.add(parent_id)

                    # Считаем MD (has_annotation или has_ocr_result)
                    if attrs.get("has_annotation") or attrs.get("has_ocr_result"):
                        md_count += 1

            logger.info(
                f"get_tree_stats: doc_count={doc_count}, pdf_count={pdf_count}, "
                f"md_count={md_count}, folders_with_pdf={len(parent_ids_with_pdf)}"
            )

            return {
                "pdf_count": pdf_count,
                "md_count": md_count,
                "folders_with_pdf": len(parent_ids_with_pdf),
            }
        except Exception as e:
            logger.error(f"Failed to get tree stats: {e}")
            return {"pdf_count": 0, "md_count": 0, "folders_with_pdf": 0}
