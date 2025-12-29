"""Миксин для фильтрации дерева проектов"""
from PySide6.QtWidgets import QTreeWidgetItem

from app.tree_client import TreeNode


class TreeFilterMixin:
    """Миксин для фильтрации дерева по тексту"""
    
    def _filter_tree(self, text: str):
        """Фильтровать дерево по тексту"""
        text = text.lower().strip()
        
        if not text:
            self._show_all_items()
            return
        
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            self._filter_item(item, text)
    
    def _show_all_items(self):
        """Показать все элементы дерева"""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            self._show_item_recursive(item)
    
    def _show_item_recursive(self, item: QTreeWidgetItem):
        """Рекурсивно показать элемент и его детей"""
        item.setHidden(False)
        for i in range(item.childCount()):
            self._show_item_recursive(item.child(i))
    
    def _filter_item(self, item: QTreeWidgetItem, text: str, parent_matches: bool = False) -> bool:
        """Фильтровать элемент и его детей"""
        from PySide6.QtCore import Qt
        
        node = item.data(0, Qt.UserRole)
        if node == "placeholder":
            item.setHidden(True)
            return False
        
        item_text = item.text(0).lower()
        matches = text in item_text
        
        if isinstance(node, TreeNode):
            self._ensure_children_loaded(item, node)
        
        if parent_matches:
            item.setHidden(False)
            item.setExpanded(True)
            for i in range(item.childCount()):
                self._filter_item(item.child(i), text, parent_matches=True)
            return True
        
        has_matching_child = False
        for i in range(item.childCount()):
            child = item.child(i)
            if self._filter_item(child, text, parent_matches=matches):
                has_matching_child = True
        
        should_show = matches or has_matching_child
        item.setHidden(not should_show)
        
        if should_show and item.childCount() > 0:
            item.setExpanded(True)
        
        return should_show
    
    def _ensure_children_loaded(self, item: QTreeWidgetItem, node: TreeNode):
        """Загрузить детей если они еще не загружены"""
        from PySide6.QtCore import Qt
        
        if item.childCount() == 1:
            child = item.child(0)
            if child.data(0, Qt.UserRole) == "placeholder":
                item.removeChild(child)
                self._load_children(item, node)


