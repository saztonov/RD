"""Mixin для операций с узлами дерева проектов"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QTreeWidgetItem,
)

from app.gui.file_transfer_worker import FileTransferWorker, TransferTask, TransferType
from app.gui.tree_cache_ops import TreeCacheOperationsMixin
from app.gui.tree_folder_ops import TreeFolderOperationsMixin
from app.tree_client import NodeStatus, NodeType, TreeNode

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


NODE_ICONS = {
    # Новые типы v2
    NodeType.FOLDER: "📁",
    NodeType.DOCUMENT: "📄",
    # Legacy aliases (для обратной совместимости с данными в БД)
    "project": "📁",
    "stage": "🏗",
    "section": "📚",
    "task_folder": "📂",
    "document": "📄",
    "folder": "📁",
}


def get_node_icon(node: TreeNode) -> str:
    """Получить иконку для узла (учитывает legacy_node_type)."""
    # Сначала проверяем legacy_node_type в attributes
    legacy_type = node.legacy_node_type
    if legacy_type and legacy_type in NODE_ICONS:
        return NODE_ICONS[legacy_type]

    # Используем node_type
    if node.node_type in NODE_ICONS:
        return NODE_ICONS[node.node_type]

    # Fallback
    return "📁" if node.is_folder else "📄"

STATUS_COLORS = {
    NodeStatus.ACTIVE: "#e0e0e0",
    NodeStatus.COMPLETED: "#4caf50",
    NodeStatus.ARCHIVED: "#9e9e9e",
}


class TreeNodeOperationsMixin(TreeCacheOperationsMixin, TreeFolderOperationsMixin):
    """Миксин для CRUD операций с узлами дерева"""

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

        from app.gui.create_node_dialog import CreateNodeDialog

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

    def _get_user_role(self):
        """Получить Qt.UserRole"""
        return Qt.UserRole

    def _close_if_open(self, r2_key: str):
        """Закрыть файл в редакторе если он открыт (по r2_key)"""
        if not r2_key:
            return

        from app.gui.folder_settings_dialog import get_projects_dir

        projects_dir = get_projects_dir()
        if not projects_dir:
            return

        # Формируем локальный путь из r2_key
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/") :]
        else:
            rel_path = r2_key

        cache_path = Path(projects_dir) / "cache" / rel_path

        # Получаем главное окно
        main_window = self.window()
        if (
            not hasattr(main_window, "_current_pdf_path")
            or not main_window._current_pdf_path
        ):
            return

        # Сравниваем пути
        try:
            current_path = Path(main_window._current_pdf_path).resolve()
            target_path = cache_path.resolve()

            if current_path == target_path:
                # Закрываем файл
                if hasattr(main_window, "_clear_interface"):
                    main_window._clear_interface()
                    logger.info(f"Closed file in editor: {cache_path}")
        except Exception as e:
            logger.error(f"Error checking open file: {e}")

    def _upload_file(self, node: TreeNode):
        """Добавить файл в папку заданий (асинхронная загрузка в R2)"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if not paths:
            return

        # Создаём worker для асинхронной загрузки
        self._upload_worker = FileTransferWorker(self)
        self._upload_target_node = node

        for path in paths:
            file_path = Path(path)
            filename = file_path.name
            file_size = file_path.stat().st_size
            r2_key = f"tree_docs/{node.id}/{filename}"

            task = TransferTask(
                transfer_type=TransferType.UPLOAD,
                local_path=str(file_path),
                r2_key=r2_key,
                node_id="",  # Будет заполнен после создания узла
                file_size=file_size,
                filename=filename,
                parent_node_id=node.id,
            )
            self._upload_worker.add_task(task)

        # Подключаем сигналы
        main_window = self.window()
        self._upload_worker.progress.connect(
            lambda msg, cur, tot: main_window.show_transfer_progress(msg, cur, tot)
        )
        self._upload_worker.finished_task.connect(self._on_upload_task_finished)
        self._upload_worker.all_finished.connect(self._on_all_uploads_finished)

        # Запускаем
        self._upload_worker.start()

    def _on_upload_task_finished(self, task: TransferTask, success: bool, error: str):
        """Обработка завершения загрузки одного файла"""
        if not success:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось загрузить файл в R2:\n{task.filename}\n{error}",
            )
            return

        logger.info(f"File uploaded to R2: {task.r2_key}")

        # Проверка уникальности имени в папке
        if not self._check_name_unique(task.parent_node_id, task.filename):
            QMessageBox.warning(
                self,
                "Ошибка",
                f"Файл с именем '{task.filename}' уже существует в этой папке",
            )
            return

        # Копируем файл в локальный кэш ДО создания узла (чтобы открытие было мгновенным)
        self._copy_to_cache(task.local_path, task.r2_key)

        parent_item = self._node_map.get(task.parent_node_id)

        try:
            doc_node = self.client.add_document(
                parent_id=task.parent_node_id,
                name=task.filename,
                r2_key=task.r2_key,
                file_size=task.file_size,
            )

            if parent_item:
                if parent_item.childCount() == 1:
                    child = parent_item.child(0)
                    if child.data(0, self._get_user_role()) == "placeholder":
                        parent_item.removeChild(child)

                child_item = self._item_builder.create_item(doc_node)
                parent_item.addChild(child_item)
                parent_item.setExpanded(True)
                self.tree.setCurrentItem(child_item)
                self.highlight_document(doc_node.id)

            logger.info(f"Document added: {doc_node.id} with r2_key={task.r2_key}")
            # Сигнал с node_id и r2_key для открытия
            self.file_uploaded_r2.emit(doc_node.id, task.r2_key)

        except Exception as e:
            logger.exception(f"Failed to add document: {e}")
            QMessageBox.critical(
                self, "Ошибка", f"Файл загружен в R2, но не добавлен в дерево:\n{e}"
            )

    def _on_all_uploads_finished(self):
        """Все загрузки завершены"""
        main_window = self.window()
        main_window.hide_transfer_progress()
        self._upload_worker = None

    def _rename_related_files(self, old_r2_key: str, new_r2_key: str, node_id: str):
        """Переименовать связанные файлы (annotation.json, ocr.html, result.json)

        ВАЖНО: Переименовывает файлы в локальном кэше НЕЗАВИСИМО от наличия в R2,
        чтобы избежать потери аннотаций при работе в офлайн режиме.
        """
        from pathlib import PurePosixPath

        from rd_core.r2_storage import R2Storage

        old_stem = PurePosixPath(old_r2_key).stem
        new_stem = PurePosixPath(new_r2_key).stem
        r2_prefix = str(PurePosixPath(old_r2_key).parent)

        r2 = R2Storage()

        # Список связанных файлов для переименования
        related_files = [
            (
                f"{r2_prefix}/{old_stem}_annotation.json",
                f"{r2_prefix}/{new_stem}_annotation.json",
            ),
            (f"{r2_prefix}/{old_stem}_ocr.html", f"{r2_prefix}/{new_stem}_ocr.html"),
            (
                f"{r2_prefix}/{old_stem}_result.json",
                f"{r2_prefix}/{new_stem}_result.json",
            ),
            (
                f"{r2_prefix}/{old_stem}_document.md",
                f"{r2_prefix}/{new_stem}_document.md",
            ),
        ]

        # Переименовываем файлы
        for old_key, new_key in related_files:
            # ВСЕГДА переименовываем в локальном кэше (даже если файла нет в R2)
            # Это критически важно для сохранения аннотаций при работе в офлайн режиме
            self._rename_cache_file(old_key, new_key)

            # Переименовываем в R2 если файл там существует
            if r2.exists(old_key):
                try:
                    if r2.rename_object(old_key, new_key):
                        logger.info(f"Renamed in R2: {old_key} → {new_key}")
                except Exception as e:
                    logger.error(f"Failed to rename in R2 {old_key}: {e}")

            # Обновляем запись в node_files если существует
            self._update_node_file_r2_key(node_id, old_key, new_key)

    def _update_node_file_r2_key(self, node_id: str, old_r2_key: str, new_r2_key: str):
        """Обновить r2_key в таблице node_files"""
        try:
            node_file = self.client.get_node_file_by_r2_key(node_id, old_r2_key)
            if node_file:
                # Обновляем r2_key и file_name
                new_file_name = Path(new_r2_key).name
                self.client.update_node_file(
                    node_file.id, r2_key=new_r2_key, file_name=new_file_name
                )
                logger.info(f"Updated node_file: {old_r2_key} → {new_r2_key}")
        except Exception as e:
            logger.error(f"Failed to update node_file: {e}")

    def _rename_node(self, node: TreeNode):
        """Переименовать узел (для документов также переименовывает в R2)"""
        # Проверка блокировки документа
        if self._check_document_locked(node):
            return

        new_name, ok = QInputDialog.getText(
            self, "Переименовать", "Новое название:", text=node.name
        )
        if ok and new_name.strip() and new_name.strip() != node.name:
            try:
                new_name_clean = new_name.strip()

                # Проверка уникальности имени в папке
                if node.parent_id and not self._check_name_unique(
                    node.parent_id, new_name_clean, node.id
                ):
                    QMessageBox.warning(
                        self,
                        "Ошибка",
                        f"Элемент с именем '{new_name_clean}' уже существует в этой папке",
                    )
                    return

                # Для документов проверяем и добавляем расширение .pdf
                if node.node_type == NodeType.DOCUMENT:
                    # Проверяем что имя заканчивается на .pdf (регистронезависимо)
                    if not new_name_clean.lower().endswith(".pdf"):
                        # Автоматически добавляем расширение .pdf
                        new_name_clean = f"{new_name_clean}.pdf"
                        logger.info(
                            f"Added .pdf extension to document name: {new_name_clean}"
                        )
                        # Повторная проверка уникальности после добавления расширения
                        if node.parent_id and not self._check_name_unique(
                            node.parent_id, new_name_clean, node.id
                        ):
                            QMessageBox.warning(
                                self,
                                "Ошибка",
                                f"Элемент с именем '{new_name_clean}' уже существует в этой папке",
                            )
                            return

                # Для документов переименовываем файл в R2
                if node.node_type == NodeType.DOCUMENT:
                    old_r2_key = node.attributes.get("r2_key", "")

                    # Закрываем файл если он открыт в редакторе
                    self._close_if_open(old_r2_key)

                    if old_r2_key:
                        from pathlib import PurePosixPath

                        from rd_core.r2_storage import R2Storage

                        # Формируем новый ключ (меняем только имя файла)
                        # Используем PurePosixPath чтобы сохранить / в путях R2
                        old_path = PurePosixPath(old_r2_key)
                        new_r2_key = str(old_path.parent / new_name_clean)

                        try:
                            r2 = R2Storage()
                            # Проверяем существование файла в R2 перед переименованием
                            if not r2.exists(old_r2_key, use_cache=False):
                                logger.warning(
                                    f"File not found in R2: {old_r2_key}, updating metadata only"
                                )
                                # Файла нет в R2 - обновляем только метаданные
                                # Но связанные файлы могут существовать
                                self._rename_related_files(
                                    old_r2_key, new_r2_key, node.id
                                )
                                node.attributes["r2_key"] = new_r2_key
                                node.attributes["original_name"] = new_name_clean
                                self.client.update_node(
                                    node.id,
                                    name=new_name_clean,
                                    attributes=node.attributes,
                                )
                                self._rename_cache_file(old_r2_key, new_r2_key)
                                self._update_node_file_r2_key(
                                    node.id, old_r2_key, new_r2_key
                                )
                            elif r2.rename_object(old_r2_key, new_r2_key):
                                # Переименовываем связанные файлы
                                self._rename_related_files(
                                    old_r2_key, new_r2_key, node.id
                                )

                                # Обновляем r2_key в attributes
                                node.attributes["r2_key"] = new_r2_key
                                node.attributes["original_name"] = new_name_clean
                                self.client.update_node(
                                    node.id,
                                    name=new_name_clean,
                                    attributes=node.attributes,
                                )

                                # Переименовываем PDF в локальном кэше
                                self._rename_cache_file(old_r2_key, new_r2_key)

                                # Обновляем запись PDF в node_files
                                self._update_node_file_r2_key(
                                    node.id, old_r2_key, new_r2_key
                                )
                            else:
                                QMessageBox.warning(
                                    self,
                                    "Внимание",
                                    "Не удалось переименовать файл в R2",
                                )
                                return
                        except Exception as e:
                            logger.error(f"R2 rename error: {e}")
                            QMessageBox.warning(self, "Ошибка R2", f"Ошибка R2: {e}")
                            return
                    else:
                        self.client.update_node(node.id, name=new_name_clean)
                else:
                    self.client.update_node(node.id, name=new_name_clean)

                # Обновляем UI
                node.name = new_name_clean
                from PySide6.QtCore import QTimer

                QTimer.singleShot(100, self._refresh_tree)
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

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
        from app.tree_client import NodeType, TreeNode

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
