"""Миксин для фильтрации дерева проектов"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from app.tree_client import TreeNode


class TreeFilterMixin:
    """Миксин для фильтрации дерева по тексту с сохранением expand state."""

    # Атрибуты инициализируются в widget.py через __init__
    _search_active: bool = False
    _pre_search_expanded: set  # node_ids раскрытых перед поиском
    _pending_batch_parent_ids: list  # parent_ids для фоновой загрузки

    def _filter_tree(self, text: str):
        """Фильтровать дерево по тексту."""
        text = text.lower().strip()

        if not text:
            self._restore_pre_search_state()
            return

        # Сохраняем expand state перед первым поиском
        if not self._search_active:
            self._save_pre_search_state()
            self._search_active = True

        # Собираем parent_ids для фоновой загрузки незагруженных детей
        self._pending_batch_parent_ids = []

        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            self._filter_item(item, text)

        # Запускаем фоновую загрузку незагруженных поддеревьев
        if self._pending_batch_parent_ids:
            self._refresh_worker.request_load_children_batch(
                self._pending_batch_parent_ids
            )

    def _save_pre_search_state(self):
        """Сохранить expand/hidden state перед поиском."""
        self._pre_search_expanded = set()

        def _collect(item: QTreeWidgetItem):
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode) and item.isExpanded():
                self._pre_search_expanded.add(node.id)
            for i in range(item.childCount()):
                _collect(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            _collect(self.tree.topLevelItem(i))

    def _restore_pre_search_state(self):
        """Восстановить expand state после очистки поиска."""
        if not self._search_active:
            # Поиск не был активен — просто показать всё
            self._show_all_items()
            return

        self._search_active = False

        # Показать все элементы и восстановить expand state
        def _restore(item: QTreeWidgetItem):
            item.setHidden(False)
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode):
                should_expand = node.id in self._pre_search_expanded
                if item.isExpanded() != should_expand:
                    item.setExpanded(should_expand)
            for i in range(item.childCount()):
                _restore(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            _restore(self.tree.topLevelItem(i))

        self._pre_search_expanded = set()

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

    def _filter_item(
        self, item: QTreeWidgetItem, text: str, parent_matches: bool = False
    ) -> bool:
        """Фильтровать элемент и его детей."""
        node = item.data(0, Qt.UserRole)
        if node == "placeholder":
            item.setHidden(True)
            return False

        item_text = item.text(0).lower()
        matches = text in item_text

        # Cache-first загрузка детей
        if isinstance(node, TreeNode):
            self._ensure_children_loaded_cached(item, node)

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

    def _ensure_children_loaded_cached(self, item: QTreeWidgetItem, node: TreeNode):
        """Загрузить детей из кэша или отложить фоновую загрузку."""
        if item.childCount() != 1:
            return
        child = item.child(0)
        if child.data(0, Qt.UserRole) != "placeholder":
            return

        # Проверяем кэш
        cached = self._node_cache.get_children(node.id)
        if cached is not None:
            # Кэш есть — загружаем мгновенно
            item.removeChild(child)
            self._populate_children(item, cached)
        else:
            # Кэша нет — откладываем фоновую загрузку (не блокируем UI)
            if hasattr(self, "_pending_batch_parent_ids"):
                self._pending_batch_parent_ids.append(node.id)
