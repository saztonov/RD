"""Операции с materialized path для дерева."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class TreePathMixin:
    """Миксин для операций с materialized path"""

    def get_descendants(self, node_id: str) -> List[Any]:
        """
        Получить всех потомков узла (используя materialized path).
        Быстрее чем рекурсивные запросы для больших деревьев.
        """
        from app.tree_models import TreeNode

        node = self.get_node(node_id)
        if not node or not node.path:
            return []

        # Ищем все узлы чей path начинается с path узла + "."
        resp = self._request(
            "get",
            f"/tree_nodes?path=like.{node.path}.%&order=depth,sort_order",
        )
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_ancestors(self, node_id: str) -> List[Any]:
        """
        Получить всех предков узла (от корня к узлу).
        Использует materialized path для эффективного запроса.
        """
        from app.tree_models import TreeNode

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

    def move_node_v2(self, node_id: str, new_parent_id: str | None) -> bool:
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

    def get_tree_stats(self) -> Dict[str, int]:
        """
        Получить общую статистику дерева для текущего клиента.
        Возвращает: pdf_count, md_count, folders_with_pdf

        Оптимизировано: вместо SELECT * LIMIT 10000 используем
        отдельные COUNT запросы для уменьшения нагрузки.
        """
        try:
            # Запрос 1: Считаем документы с PDF
            resp_docs = self._request(
                "get",
                "/tree_nodes?node_type=eq.document&select=id,parent_id,attributes",
            )
            docs = resp_docs.json()

            pdf_count = 0
            md_count = 0
            parent_ids_with_pdf = set()

            for doc in docs:
                attrs = doc.get("attributes") or {}
                r2_key = attrs.get("r2_key", "")

                # Считаем PDF
                if r2_key.lower().endswith(".pdf"):
                    pdf_count += 1
                    parent_id = doc.get("parent_id")
                    if parent_id:
                        parent_ids_with_pdf.add(parent_id)

                # Считаем MD (has_annotation или has_ocr_result)
                if attrs.get("has_annotation") or attrs.get("has_ocr_result"):
                    md_count += 1

            logger.info(
                f"get_tree_stats: doc_count={len(docs)}, pdf_count={pdf_count}, "
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
