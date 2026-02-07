"""Миксин загрузки и обновления дерева проектов."""

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTreeWidgetItem

logger = logging.getLogger(__name__)


class TreeLoadMixin:
    """Начальная загрузка, обновление, lazy loading дерева."""

    def _initial_load(self):
        """Начальная загрузка (асинхронно через QThread)"""
        if not self.client.is_available():
            self.status_label.setText("⚠ Supabase недоступен")
            return

        self._load_expanded_state()
        self._loading = True
        self._pdf_status_manager.reset()
        self.status_label.setText("⏳ Загрузка дерева...")
        self.tree.clear()
        self._node_map.clear()
        self._sync_statuses.clear()

        from .initial_load_worker import InitialLoadWorker

        self._initial_load_worker = InitialLoadWorker(self.client, self)
        self._initial_load_worker.types_loaded.connect(self._on_types_loaded)
        self._initial_load_worker.roots_loaded.connect(self._on_roots_loaded)
        self._initial_load_worker.stats_loaded.connect(self._on_stats_loaded)
        self._initial_load_worker.statuses_loaded.connect(self._on_statuses_loaded)
        self._initial_load_worker.error.connect(self._on_load_error)
        self._initial_load_worker.finished_all.connect(self._on_load_finished)
        self._initial_load_worker.start()

    def _on_types_loaded(self, stage_types: list, section_types: list):
        """Обработка загруженных типов"""
        self._stage_types = stage_types
        self._section_types = section_types

    def _on_roots_loaded(self, roots: list):
        """Обработка корневых узлов"""
        from app.tree_client import NodeType, TreeNode

        self._last_node_count = len(roots)
        for node in roots:
            item = self._item_builder.create_item(node)
            self.tree.addTopLevelItem(item)
            self._item_builder.add_placeholder(item, node)

        self.status_label.setText(f"Проектов: {len(roots)}")

        doc_ids = []
        for node_id, item in self._node_map.items():
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode) and node.node_type == NodeType.DOCUMENT:
                doc_ids.append(node_id)

        if self._initial_load_worker and doc_ids:
            self._initial_load_worker.set_doc_ids(doc_ids)

    def _on_stats_loaded(self, stats: dict):
        """Обработка статистики дерева"""
        pdf_count = stats.get("pdf_count", 0)
        md_count = stats.get("md_count", 0)
        folders_with_pdf = stats.get("folders_with_pdf", 0)
        self.stats_label.setText(
            f"📄 PDF: {pdf_count}  |  📝 MD: {md_count}  |  📁 Папок с PDF: {folders_with_pdf}"
        )

    def _on_statuses_loaded(self, statuses: dict):
        """Обработка PDF статусов"""
        self._pdf_status_manager.apply_statuses(statuses)

    def _on_load_error(self, error_msg: str):
        """Обработка ошибки загрузки"""
        logger.error(f"Initial load error: {error_msg}")
        self.status_label.setText(f"⚠ Ошибка: {error_msg[:50]}")
        self._loading = False

    def _on_load_finished(self):
        """Загрузка завершена"""
        self._loading = False
        QTimer.singleShot(100, self._restore_expanded_state)
        QTimer.singleShot(500, self._start_sync_check)

    def _refresh_tree(self):
        """Обновить дерево"""
        if self._loading:
            return

        self._loading = True
        self._pdf_status_manager.reset()
        self.status_label.setText("Загрузка...")
        self.tree.clear()
        self._node_map.clear()
        self._sync_statuses.clear()

        try:
            roots = self.client.get_root_nodes()
            self._last_node_count = len(roots)
            for node in roots:
                item = self._item_builder.create_item(node)
                self.tree.addTopLevelItem(item)
                self._item_builder.add_placeholder(item, node)

            self.status_label.setText(f"Проектов: {len(roots)}")

            QTimer.singleShot(100, self._restore_expanded_state)
            QTimer.singleShot(300, self._update_stats)
            QTimer.singleShot(500, self._start_sync_check)

            if not self._pdf_status_manager.is_loaded:
                QTimer.singleShot(200, self._pdf_status_manager.load_batch)
        except Exception as e:
            logger.error(f"Failed to refresh tree: {e}")
            self.status_label.setText(f"Ошибка: {e}")
        finally:
            self._loading = False

    def _auto_refresh_tree(self):
        """Автоматическое обновление дерева"""
        from app.tree_client import TreeNode

        if self._loading:
            return

        try:
            roots = self.client.get_root_nodes()
            current_count = len(roots)

            if current_count != self._last_node_count:
                self._last_node_count = current_count
                self._refresh_tree()
                return

            for root in roots:
                if root.id in self._node_map:
                    item = self._node_map[root.id]
                    old_node = item.data(0, Qt.UserRole)
                    if isinstance(old_node, TreeNode):
                        if old_node.updated_at != root.updated_at:
                            self._refresh_tree()
                            return
                else:
                    self._refresh_tree()
                    return
        except Exception as e:
            logger.debug(f"Auto-refresh check failed: {e}")

    def _load_children(self, parent_item: QTreeWidgetItem, parent_node):
        """Загрузить дочерние узлы"""
        try:
            children = self.client.get_children(parent_node.id)
            for child in children:
                child_item = self._item_builder.create_item(child)
                parent_item.addChild(child_item)
                self._item_builder.add_placeholder(child_item, child)
        except Exception as e:
            logger.error(f"Failed to load children: {e}")

    def _update_stats(self):
        """Обновить статистику документов"""
        try:
            stats = self.client.get_tree_stats()
            pdf_count = stats.get("pdf_count", 0)
            md_count = stats.get("md_count", 0)
            folders_with_pdf = stats.get("folders_with_pdf", 0)
            self.stats_label.setText(
                f"📄 PDF: {pdf_count}  |  📝 MD: {md_count}  |  📁 Папок с PDF: {folders_with_pdf}"
            )
        except Exception as e:
            logger.debug(f"Failed to update stats: {e}")
            self.stats_label.setText("")
