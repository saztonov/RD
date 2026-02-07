"""Миксин перемещения узлов (вверх/вниз) в дереве."""

import logging

from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class TreeReorderMixin:
    """Перемещение узлов вверх/вниз по дереву."""

    def _move_node_up(self, node):
        """Переместить узел вверх (уменьшить sort_order)"""
        self._move_node(node, direction=-1)

    def _move_node_down(self, node):
        """Переместить узел вниз (увеличить sort_order)"""
        self._move_node(node, direction=1)

    def _move_node(self, node, direction: int):
        """Переместить узел в указанном направлении (-1 = вверх, 1 = вниз)"""
        try:
            current_item = self._node_map.get(node.id)
            if not current_item:
                return

            parent_item = current_item.parent()
            if parent_item:
                current_idx = parent_item.indexOfChild(current_item)
                child_count = parent_item.childCount()
            else:
                current_idx = self.tree.indexOfTopLevelItem(current_item)
                child_count = self.tree.topLevelItemCount()

            swap_idx = current_idx + direction
            if swap_idx < 0 or swap_idx >= child_count:
                self.status_label.setText("⚠ Узел уже на границе")
                return

            if node.parent_id:
                siblings = self.client.get_children(node.parent_id)
            else:
                siblings = self.client.get_root_nodes()

            current_node = None
            swap_node = None
            for sibling in siblings:
                if sibling.id == node.id:
                    current_node = sibling
                elif swap_idx < current_idx and sibling.id == self._get_sibling_id(parent_item, swap_idx):
                    swap_node = sibling
                elif swap_idx > current_idx and sibling.id == self._get_sibling_id(parent_item, swap_idx):
                    swap_node = sibling

            if not current_node or not swap_node:
                for i, sibling in enumerate(siblings):
                    if sibling.id == node.id:
                        db_current_idx = i
                        break
                db_swap_idx = db_current_idx + direction
                if 0 <= db_swap_idx < len(siblings):
                    current_node = siblings[db_current_idx]
                    swap_node = siblings[db_swap_idx]

            if not current_node or not swap_node:
                self._refresh_tree()
                return

            current_sort = current_node.sort_order
            swap_sort = swap_node.sort_order

            if current_sort == swap_sort:
                for i, sibling in enumerate(siblings):
                    new_order = i * 10
                    if sibling.sort_order != new_order:
                        self.client.update_node(sibling.id, sort_order=new_order)
                for i, sibling in enumerate(siblings):
                    if sibling.id == node.id:
                        db_current_idx = i
                        break
                db_swap_idx = db_current_idx + direction
                self.client.update_node(current_node.id, sort_order=db_swap_idx * 10)
                self.client.update_node(swap_node.id, sort_order=db_current_idx * 10)
            else:
                self.client.update_node(current_node.id, sort_order=swap_sort)
                self.client.update_node(swap_node.id, sort_order=current_sort)

            if parent_item:
                item = parent_item.takeChild(current_idx)
                parent_item.insertChild(swap_idx, item)
            else:
                item = self.tree.takeTopLevelItem(current_idx)
                self.tree.insertTopLevelItem(swap_idx, item)

            self.tree.setCurrentItem(item)
            self.status_label.setText("✓ Узел перемещён")

        except Exception as e:
            logger.error(f"Failed to move node: {e}")
            self.status_label.setText(f"Ошибка перемещения: {e}")

    def _get_sibling_id(self, parent_item, idx: int) -> str:
        """Получить ID узла по индексу в родителе"""
        from app.tree_client import TreeNode

        if parent_item:
            child = parent_item.child(idx)
        else:
            child = self.tree.topLevelItem(idx)
        if child:
            node = child.data(0, Qt.UserRole)
            if isinstance(node, TreeNode):
                return node.id
        return ""
