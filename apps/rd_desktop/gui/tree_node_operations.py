"""Mixin для операций с узлами дерева проектов

Модуль разбит на компоненты:
- tree_constants.py: NODE_ICONS, STATUS_COLORS, get_node_icon
- tree_upload_mixin.py: загрузка файлов в R2
- tree_rename_mixin.py: переименование узлов и файлов
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QMessageBox,
)

from apps.rd_desktop.gui.tree_cache_ops import TreeCacheOperationsMixin
from apps.rd_desktop.gui.tree_constants import NODE_ICONS, STATUS_COLORS, get_node_icon
from apps.rd_desktop.gui.tree_folder_ops import TreeFolderOperationsMixin
from apps.rd_desktop.gui.tree_rename_mixin import TreeRenameMixin
from apps.rd_desktop.gui.tree_upload_mixin import TreeUploadMixin
from apps.rd_desktop.tree_client import NodeStatus, NodeType, TreeNode

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Реэкспорт для обратной совместимости
__all__ = [
    "NODE_ICONS",
    "STATUS_COLORS",
    "get_node_icon",
    "TreeNodeOperationsMixin",
]


class TreeNodeOperationsMixin(
    TreeCacheOperationsMixin,
    TreeFolderOperationsMixin,
    TreeUploadMixin,
    TreeRenameMixin,
):
    """Миксин для CRUD операций с узлами дерева"""

    def _pause_timers(self):
        """Приостановить фоновые таймеры на время показа диалога"""
        if hasattr(self, '_auto_refresh_timer') and self._auto_refresh_timer:
            self._auto_refresh_timer.stop()
        if hasattr(self, '_pdf_status_refresh_timer') and self._pdf_status_refresh_timer:
            self._pdf_status_refresh_timer.stop()

    def _resume_timers(self):
        """Возобновить фоновые таймеры после закрытия диалога"""
        if hasattr(self, '_auto_refresh_timer') and self._auto_refresh_timer:
            self._auto_refresh_timer.start(30000)
        if hasattr(self, '_pdf_status_refresh_timer') and self._pdf_status_refresh_timer:
            self._pdf_status_refresh_timer.start(30000)

    def _check_name_unique(
        self, parent_id: str, name: str, exclude_node_id: str = None
    ) -> bool:
        """Проверить уникальность имени в папке. True если уникально."""
        siblings = self.client.get_children(parent_id)
        for s in siblings:
            if s.name == name and s.id != exclude_node_id:
                return False
        return True

    def _create_project(self):
        """Создать новый проект (корневая папка)"""
        self._pause_timers()
        try:
            name, ok = QInputDialog.getText(self, "Новый проект", "Название проекта:")
            if ok and name.strip():
                try:
                    # Создаём корневую папку (FOLDER вместо PROJECT)
                    node = self.client.create_node(NodeType.FOLDER, name.strip())
                    item = self._item_builder.create_item(node)
                    self.tree.addTopLevelItem(item)
                    self._item_builder.add_placeholder(item, node)
                    self.tree.setCurrentItem(item)
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", str(e))
        finally:
            self._resume_timers()

    def _create_child_node(self, parent_node: TreeNode, child_type):
        """Создать дочерний узел"""
        if isinstance(child_type, str):
            logger.debug(f"child_type is str: {child_type}, converting to NodeType")
            child_type = NodeType(child_type)

        logger.debug(
            f"_create_child_node: parent={parent_node.id}, child_type={child_type}"
        )

        stage_types = self._stage_types if child_type == NodeType.STAGE else None
        section_types = self._section_types if child_type == NodeType.SECTION else None

        from apps.rd_desktop.gui.create_node_dialog import CreateNodeDialog

        self._pause_timers()
        try:
            dialog = CreateNodeDialog(self, child_type, stage_types, section_types)
            if dialog.exec_() == QDialog.Accepted:
                name, code = dialog.get_data()
                logger.debug(f"Dialog result: name={name}, code={code}")
                if name:
                    try:
                        logger.debug(
                            f"Creating node: type={child_type}, name={name}, parent={parent_node.id}, code={code}"
                        )
                        node = self.client.create_node(
                            child_type, name, parent_node.id, code
                        )
                        logger.debug(f"Node created: {node.id}")
                        parent_item = self._node_map.get(parent_node.id)
                        if parent_item:
                            if parent_item.childCount() == 1:
                                child = parent_item.child(0)
                                if child.data(0, self._get_user_role()) == "placeholder":
                                    parent_item.removeChild(child)

                            child_item = self._item_builder.create_item(node)
                            parent_item.addChild(child_item)
                            self._item_builder.add_placeholder(child_item, node)
                            parent_item.setExpanded(True)
                            self.tree.setCurrentItem(child_item)
                    except Exception as e:
                        logger.exception(f"Error creating child node: {e}")
                        QMessageBox.critical(self, "Ошибка", str(e))
        finally:
            self._resume_timers()

    def _get_user_role(self):
        """Получить Qt.UserRole"""
        return Qt.UserRole

    def _set_status(self, node: TreeNode, status: NodeStatus):
        """Установить статус узла"""
        try:
            self.client.update_node(node.id, status=status)
            item = self._node_map.get(node.id)
            if item:
                item.setForeground(0, QColor(STATUS_COLORS.get(status, "#e0e0e0")))
                node.status = status
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _set_document_version(self, node: TreeNode, version: int):
        """Установить версию документа"""
        try:
            self.client.update_node(node.id, version=version)
            node.version = version

            # Обновляем отображение в дереве
            item = self._node_map.get(node.id)
            if item:
                icon = NODE_ICONS.get(node.node_type, "📄")
                has_annotation = node.attributes.get("has_annotation", False)
                ann_icon = " 📋" if has_annotation else ""
                display_name = f"{icon} {node.name}{ann_icon}"
                item.setText(0, display_name)
                item.setData(0, Qt.UserRole + 1, f"[v{version}]")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _delete_node(self, node: TreeNode):
        """Удалить узел и все вложенные (из R2, кэша и Supabase)"""
        # Проверка блокировки документа
        if self._check_document_locked(node):
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить '{node.name}' и все вложенные элементы?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                # Рекурсивно удаляем все документы в ветке из R2 и кэша
                self._delete_branch_files(node)

                if self.client.delete_node(node.id):
                    item = self._node_map.get(node.id)
                    if item:
                        # Рекурсивно собрать все id дочерних элементов
                        def collect_child_ids(parent_item):
                            ids = []
                            for i in range(parent_item.childCount()):
                                child_item = parent_item.child(i)
                                child_node = child_item.data(0, Qt.UserRole)
                                if isinstance(child_node, TreeNode):
                                    ids.append(child_node.id)
                                    ids.extend(collect_child_ids(child_item))
                            return ids

                        child_ids = collect_child_ids(item)

                        # Очистить _node_map и _expanded_nodes для всех дочерних
                        for cid in child_ids:
                            self._node_map.pop(cid, None)
                            self._expanded_nodes.discard(cid)

                        # Удалить сам узел из _node_map и _expanded_nodes
                        del self._node_map[node.id]
                        self._expanded_nodes.discard(node.id)
                        self._save_expanded_state()

                        # Обновить счётчик узлов чтобы auto_refresh не триггерился
                        if hasattr(self, '_last_node_count') and self._last_node_count > 0:
                            self._last_node_count -= 1

                        # Удалить элемент из UI
                        parent = item.parent()
                        if parent:
                            parent.removeChild(item)
                        else:
                            idx = self.tree.indexOfTopLevelItem(item)
                            self.tree.takeTopLevelItem(idx)
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _delete_nodes(self, nodes: List["TreeNode"]):
        """Удалить несколько узлов и все вложенные (из R2, кэша и Supabase)"""
        from apps.rd_desktop.tree_client import NodeType, TreeNode

        # Проверка блокировки документов
        locked = [
            n for n in nodes if n.node_type == NodeType.DOCUMENT and n.is_locked
        ]
        if locked:
            QMessageBox.warning(
                self,
                "Заблокировано",
                f"{len(locked)} документов заблокированы и не будут удалены",
            )
            nodes = [n for n in nodes if n not in locked]

        if not nodes:
            return

        # Формируем список имён для подтверждения
        names = "\n".join(f"• {n.name}" for n in nodes[:5])
        if len(nodes) > 5:
            names += f"\n... и ещё {len(nodes) - 5}"

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить {len(nodes)} элементов?\n\n{names}",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            deleted_count = 0
            for node in nodes:
                try:
                    # Рекурсивно удаляем все документы в ветке из R2 и кэша
                    self._delete_branch_files(node)

                    if self.client.delete_node(node.id):
                        item = self._node_map.get(node.id)
                        if item:
                            # Рекурсивно собрать все id дочерних
                            def collect_child_ids(parent_item):
                                ids = []
                                for i in range(parent_item.childCount()):
                                    child_item = parent_item.child(i)
                                    child_node = child_item.data(0, Qt.UserRole)
                                    if isinstance(child_node, TreeNode):
                                        ids.append(child_node.id)
                                        ids.extend(collect_child_ids(child_item))
                                return ids

                            child_ids = collect_child_ids(item)

                            # Очистить _node_map и _expanded_nodes для всех дочерних
                            for cid in child_ids:
                                self._node_map.pop(cid, None)
                                self._expanded_nodes.discard(cid)

                            # Удалить сам узел из _node_map и _expanded_nodes
                            self._node_map.pop(node.id, None)
                            self._expanded_nodes.discard(node.id)

                            # Обновить счётчик узлов
                            if hasattr(self, "_last_node_count") and self._last_node_count > 0:
                                self._last_node_count -= 1

                            # Удалить элемент из UI
                            parent = item.parent()
                            if parent:
                                parent.removeChild(item)
                            else:
                                idx = self.tree.indexOfTopLevelItem(item)
                                self.tree.takeTopLevelItem(idx)

                        deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete {node.name}: {e}")

            # Сохранить состояние раскрытых узлов
            self._save_expanded_state()
            self.status_label.setText(f"Удалено {deleted_count} элементов")
