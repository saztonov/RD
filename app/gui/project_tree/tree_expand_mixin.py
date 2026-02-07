"""Миксин управления раскрытием/свёртыванием дерева."""

import logging

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QTreeWidgetItem

logger = logging.getLogger(__name__)


class TreeExpandMixin:
    """Раскрытие/свёртывание и сохранение состояния дерева."""

    def _expand_selected(self):
        """Развернуть выбранную папку рекурсивно или всё дерево"""
        from app.tree_client import TreeNode

        item = self.tree.currentItem()
        if item:
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode) and node.is_folder:
                self._expand_item_recursively(item)
                return
        self.tree.expandAll()

    def _collapse_selected(self):
        """Свернуть выбранную папку рекурсивно или всё дерево"""
        from app.tree_client import TreeNode

        item = self.tree.currentItem()
        if item:
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode) and node.is_folder:
                self._collapse_item_recursively(item)
                return
        self.tree.collapseAll()

    def _expand_item_recursively(self, item: QTreeWidgetItem):
        """Рекурсивно развернуть элемент и всех его детей"""
        from app.tree_client import TreeNode

        item.setExpanded(True)
        for i in range(item.childCount()):
            child = item.child(i)
            child_node = child.data(0, Qt.UserRole)
            if isinstance(child_node, TreeNode) and child_node.is_folder:
                self._expand_item_recursively(child)

    def _collapse_item_recursively(self, item: QTreeWidgetItem):
        """Рекурсивно свернуть элемент и всех его детей"""
        from app.tree_client import TreeNode

        for i in range(item.childCount()):
            child = item.child(i)
            child_node = child.data(0, Qt.UserRole)
            if isinstance(child_node, TreeNode) and child_node.is_folder:
                self._collapse_item_recursively(child)
        item.setExpanded(False)

    def _save_expanded_state(self):
        try:
            settings = QSettings("RDApp", "ProjectTree")
            settings.setValue("expanded_nodes", list(self._expanded_nodes))
        except Exception as e:
            logger.debug(f"Failed to save expanded state: {e}")

    def _load_expanded_state(self):
        try:
            settings = QSettings("RDApp", "ProjectTree")
            expanded_list = settings.value("expanded_nodes", [])
            self._expanded_nodes = set(expanded_list) if expanded_list else set()
        except Exception as e:
            logger.debug(f"Failed to load expanded state: {e}")
            self._expanded_nodes = set()

    def _restore_expanded_state(self):
        from app.tree_client import TreeNode

        if not self._expanded_nodes:
            return

        def expand_recursive(item: QTreeWidgetItem):
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode) and node.id in self._expanded_nodes:
                item.setExpanded(True)
                for i in range(item.childCount()):
                    expand_recursive(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            expand_recursive(self.tree.topLevelItem(i))
