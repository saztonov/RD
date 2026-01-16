"""Миксин для синхронизации дерева проектов с R2"""
import logging
from pathlib import Path
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from apps.rd_desktop.gui.sync_check_worker import SyncCheckWorker, SyncStatus
from apps.rd_desktop.tree_client import NodeType, TreeNode

logger = logging.getLogger(__name__)

# Иконки статуса синхронизации
SYNC_ICONS = {
    SyncStatus.SYNCED: "✅",
    SyncStatus.NOT_SYNCED: "⚠️",
    SyncStatus.MISSING_LOCAL: "📥",
    SyncStatus.CHECKING: "🔄",
    SyncStatus.UNKNOWN: "",
}


class TreeSyncMixin:
    """Миксин для проверки синхронизации с R2"""

    _sync_statuses: Dict[str, SyncStatus]
    _sync_worker: SyncCheckWorker

    def _start_sync_check(self):
        """Запустить фоновую проверку синхронизации всех TASK_FOLDER и DOCUMENT"""
        from apps.rd_desktop.gui.folder_settings_dialog import get_projects_dir

        projects_dir = get_projects_dir()
        if not projects_dir:
            logger.debug("Projects dir not set, skipping sync check")
            return

        # Останавливаем предыдущий воркер если есть
        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_worker.stop()

        self._sync_worker = SyncCheckWorker(self)
        self._sync_worker.result_ready.connect(self._on_sync_check_result)
        self._sync_worker.check_finished.connect(self._on_sync_check_finished)

        # Собираем узлы для проверки (TASK_FOLDER и DOCUMENT)
        self._collect_nodes_for_sync_check(self._sync_worker, projects_dir)

        if self._sync_worker._nodes_to_check:
            logger.debug(
                f"Starting sync check for {len(self._sync_worker._nodes_to_check)} nodes"
            )
            self._sync_worker.start()

    def _collect_nodes_for_sync_check(self, worker: SyncCheckWorker, projects_dir: str):
        """Рекурсивно собрать все TASK_FOLDER и DOCUMENT для проверки"""

        def collect_from_item(item: QTreeWidgetItem):
            node = item.data(0, Qt.UserRole)
            if not isinstance(node, TreeNode):
                return

            if node.node_type == NodeType.TASK_FOLDER:
                # Для TASK_FOLDER проверяем все файлы по префиксу
                r2_prefix = f"tree_docs/{node.id}/"
                local_folder = str(Path(projects_dir) / "cache" / node.id)
                worker.add_check(node.id, r2_prefix, local_folder)

            elif node.node_type == NodeType.DOCUMENT:
                # Для DOCUMENT проверяем конкретный файл
                r2_key = node.attributes.get("r2_key", "")
                if r2_key:
                    if r2_key.startswith("tree_docs/"):
                        rel_path = r2_key[len("tree_docs/") :]
                    else:
                        rel_path = r2_key
                    local_folder = str(
                        Path(projects_dir) / "cache" / Path(rel_path).parent
                    )
                    worker.add_check(node.id, r2_key, local_folder)

            # Рекурсивно для дочерних
            for i in range(item.childCount()):
                collect_from_item(item.child(i))

        # Обходим все корневые элементы
        for i in range(self.tree.topLevelItemCount()):
            collect_from_item(self.tree.topLevelItem(i))

    def _on_sync_check_result(self, node_id: str, status_value: str):
        """Обработать результат проверки синхронизации"""
        try:
            status = SyncStatus(status_value)
        except ValueError:
            status = SyncStatus.UNKNOWN

        self._sync_statuses[node_id] = status

        # Обновляем отображение узла
        item = self._node_map.get(node_id)
        if item:
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode):
                self._update_item_sync_icon(item, node, status)

    def _update_item_sync_icon(
        self, item: QTreeWidgetItem, node: TreeNode, status: SyncStatus
    ):
        """Обновить иконку синхронизации для элемента дерева"""
        from apps.rd_desktop.gui.tree_node_operations import NODE_ICONS

        icon = NODE_ICONS.get(node.node_type, "📄")

        # НЕ ПОКАЗЫВАЕМ иконки синхронизации - ни для документов, ни для папок
        # Для документов используем только PDF status icons
        # Для папок - никаких иконок статуса

        if node.node_type == NodeType.DOCUMENT:
            # Для документов используем PDF status вместо sync status
            # Запускаем проверку PDF статуса если миксин доступен
            if hasattr(self, "_start_pdf_status_check"):
                # Проверка будет выполнена асинхронно
                pass
        elif node.node_type == NodeType.TASK_FOLDER:
            # Убираем иконки синхронизации для папок
            if node.code:
                display_name = f"{icon} [{node.code}] {node.name}".strip()
            else:
                display_name = f"{icon} {node.name}".strip()
            item.setText(0, display_name)

    def _on_sync_check_finished(self):
        """Проверка синхронизации завершена"""
        logger.debug("Sync check finished")
        self._sync_worker = None

    def check_sync_status(self):
        """Публичный метод для запуска проверки синхронизации"""
        self._start_sync_check()
