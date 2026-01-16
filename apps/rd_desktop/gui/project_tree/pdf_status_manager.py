"""Управление статусами PDF документов в дереве проектов"""
import logging
from typing import TYPE_CHECKING, Dict

from PySide6.QtCore import Qt

from apps.rd_desktop.tree_client import NodeType, TreeNode

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTreeWidgetItem

logger = logging.getLogger(__name__)

# Иконки статусов PDF
PDF_STATUS_ICONS = {
    "complete": "✅",
    "missing_files": "⚠️",
    "missing_blocks": "❌",
    "unknown": "",
}


class PDFStatusManager:
    """
    Менеджер статусов PDF документов.

    Отвечает за:
    - Загрузку статусов батчем
    - Автоматическое обновление статусов
    - Кэширование и очистку
    """

    def __init__(self, widget: "ProjectTreeWidget"):
        """
        Args:
            widget: Родительский виджет ProjectTreeWidget
        """
        self._widget = widget
        self._pdf_statuses_loaded = False

    @property
    def is_loaded(self) -> bool:
        """Загружены ли статусы"""
        return self._pdf_statuses_loaded

    def reset(self) -> None:
        """Сбросить флаг загрузки"""
        self._pdf_statuses_loaded = False

    def mark_loaded(self) -> None:
        """Отметить статусы как загруженные"""
        self._pdf_statuses_loaded = True

    @staticmethod
    def get_status_icon(status: str) -> str:
        """Получить иконку для статуса PDF"""
        return PDF_STATUS_ICONS.get(status, "")

    def load_batch(self) -> None:
        """Загрузить статусы всех PDF документов батчем"""
        from apps.rd_desktop.gui.tree_node_operations import NODE_ICONS

        try:
            # Собираем ID всех документов
            doc_ids = []
            for node_id, item in self._widget._node_map.items():
                node = item.data(0, Qt.UserRole)
                if isinstance(node, TreeNode) and node.node_type == NodeType.DOCUMENT:
                    doc_ids.append(node_id)

            if not doc_ids:
                self._pdf_statuses_loaded = True
                return

            logger.debug(f"Loading PDF statuses for {len(doc_ids)} documents")

            # Загружаем батчем
            statuses = self._widget.client.get_pdf_statuses_batch(doc_ids)

            # Обновляем отображение для ВСЕХ документов
            for node_id in doc_ids:
                item = self._widget._node_map.get(node_id)
                if item:
                    node = item.data(0, Qt.UserRole)
                    if isinstance(node, TreeNode) and node.node_type == NodeType.DOCUMENT:
                        status, message = statuses.get(node_id, ("unknown", ""))

                        # Обновляем кешированные значения в узле
                        node.pdf_status = status
                        node.pdf_status_message = message

                        # Обновляем отображение
                        self._update_item_display(item, node, status, message)

            self._pdf_statuses_loaded = True
            logger.info(f"Loaded PDF statuses: {len(statuses)}/{len(doc_ids)} documents")

        except Exception as e:
            logger.error(f"Failed to load PDF statuses batch: {e}")
            self._pdf_statuses_loaded = True

    def auto_refresh(self) -> None:
        """Автоматическое обновление статусов PDF (без полного обновления дерева)"""
        if self._widget._loading or not self._pdf_statuses_loaded:
            return

        try:
            # Собираем ID всех документов
            doc_ids = []
            for node_id, item in self._widget._node_map.items():
                node = item.data(0, Qt.UserRole)
                if isinstance(node, TreeNode) and node.node_type == NodeType.DOCUMENT:
                    doc_ids.append(node_id)

            if not doc_ids:
                return

            # Получаем свежие статусы из БД
            fresh_statuses = self._widget.client.get_pdf_statuses_batch_fresh(doc_ids)

            # Получаем кеш для обновления
            from apps.rd_desktop.gui.pdf_status_cache import get_pdf_status_cache
            cache = get_pdf_status_cache()

            # Обновляем только изменившиеся статусы
            updated_count = 0
            for node_id in doc_ids:
                item = self._widget._node_map.get(node_id)
                if not item:
                    continue

                node = item.data(0, Qt.UserRole)
                if not isinstance(node, TreeNode) or node.node_type != NodeType.DOCUMENT:
                    continue

                new_status, new_message = fresh_statuses.get(node_id, ("unknown", ""))
                old_status = node.pdf_status or "unknown"

                # Обновляем кеш
                cache.set(node_id, new_status, new_message)

                # Если статус изменился - обновляем отображение
                if new_status != old_status:
                    node.pdf_status = new_status
                    node.pdf_status_message = new_message

                    self._update_item_display(item, node, new_status, new_message)
                    updated_count += 1
                    logger.debug(f"PDF status updated: {node.name} {old_status} -> {new_status}")

            if updated_count > 0:
                logger.info(f"Auto-refreshed {updated_count} PDF status(es)")

        except Exception as e:
            logger.debug(f"Auto-refresh PDF statuses failed: {e}")

    def cleanup_cache(self) -> None:
        """Периодическая очистка истёкших записей из кеша"""
        try:
            from apps.rd_desktop.gui.pdf_status_cache import get_pdf_status_cache

            cache = get_pdf_status_cache()
            cleaned = cache.cleanup_expired()
            if cleaned > 0:
                logger.debug(f"Cleaned {cleaned} expired PDF status cache entries")
        except Exception as e:
            logger.error(f"PDF cache cleanup failed: {e}")

    def _update_item_display(
        self,
        item: "QTreeWidgetItem",
        node: TreeNode,
        status: str,
        message: str
    ) -> None:
        """Обновить отображение элемента дерева"""
        from apps.rd_desktop.gui.tree_node_operations import NODE_ICONS

        icon = NODE_ICONS.get(node.node_type, "📄")
        status_icon = self.get_status_icon(status)
        lock_icon = "🔒" if node.is_locked else ""
        version_tag = f"[v{node.version}]" if node.version else "[v1]"

        display_name = f"{icon} {node.name} {lock_icon} {status_icon}".strip()
        item.setText(0, display_name)
        item.setData(0, Qt.UserRole + 1, version_tag)

        if message:
            item.setToolTip(0, message)
        else:
            item.setToolTip(0, "")


# Type hint for circular import
if TYPE_CHECKING:
    from apps.rd_desktop.gui.project_tree.widget import ProjectTreeWidget
