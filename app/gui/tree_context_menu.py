"""Миксин для контекстного меню дерева проектов"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from app.tree_client import NodeType, TreeNode

logger = logging.getLogger(__name__)


class TreeContextMenuMixin:
    """Миксин для контекстного меню дерева"""

    def _show_context_menu(self, pos):
        """Показать контекстное меню"""
        from app.gui.folder_settings_dialog import get_max_versions

        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        if item:
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode):
                # v2: Для папок показываем "Добавить папку" и "Добавить файл"
                if node.is_folder:
                    action = menu.addAction("📁 Добавить папку")
                    action.setData(("add", NodeType.FOLDER, node))

                    action = menu.addAction("📄 Добавить файл")
                    action.setData(("upload", node))

                # Перемещение вверх/вниз (для всех узлов)
                menu.addSeparator()
                action = menu.addAction("⬆️ Переместить вверх")
                action.setData(("move_up", node))
                action = menu.addAction("⬇️ Переместить вниз")
                action.setData(("move_down", node))

                if node.is_document:
                    # Открыть папку с файлами
                    action = menu.addAction("📂 Открыть папку")
                    action.setData(("open_folder", node))

                    # Блокировка/разблокировка
                    menu.addSeparator()
                    if node.is_locked:
                        action = menu.addAction("🔓 Снять блокировку")
                        action.setData(("unlock_document", node))
                    else:
                        action = menu.addAction("🔒 Заблокировать документ")
                        action.setData(("lock_document", node))
                    menu.addSeparator()

                    # Подменю выбора версии
                    max_versions = get_max_versions()
                    version_menu = menu.addMenu(f"📌 Версия [v{node.version or 1}]")
                    for v in range(1, max_versions + 1):
                        v_action = version_menu.addAction(f"v{v}")
                        v_action.setData(("set_version", node, v))
                        if v == (node.version or 1):
                            v_action.setCheckable(True)
                            v_action.setChecked(True)

                    r2_key = node.attributes.get("r2_key", "")
                    if r2_key and r2_key.lower().endswith(".pdf"):
                        action = menu.addAction("🗑️ Удалить рамки/QR")
                        action.setData(("remove_stamps", node))

                        action = menu.addAction("✂️ Разделить документ")
                        action.setData(("split_document", node))

                    # Копировать/вставить аннотацию
                    has_annotation = node.attributes.get("has_annotation", False)
                    if has_annotation and r2_key:
                        action = menu.addAction("📋 Скопировать аннотацию")
                        action.setData(("copy_annotation", node))

                    if self._copied_annotation and r2_key:
                        action = menu.addAction("📥 Вставить аннотацию")
                        action.setData(("paste_annotation", node))

                    # Загрузить аннотацию из файла
                    if r2_key:
                        action = menu.addAction("📤 Загрузить аннотацию блоков")
                        action.setData(("upload_annotation", node))

                    # Определить и назначить штамп
                    if r2_key and r2_key.lower().endswith(".pdf"):
                        action = menu.addAction("🔖 Определить и назначить штамп")
                        action.setData(("detect_stamps", node))

                    # Верификация блоков
                    if r2_key and r2_key.lower().endswith(".pdf"):
                        action = menu.addAction("🔍 Верификация блоков")
                        action.setData(("verify_blocks", node))

                    # Сверка файлов R2/Supabase (только для документов с r2_key)
                    if r2_key:
                        action = menu.addAction("🔄 Сверка R2/Supabase")
                        action.setData(("reconcile_files", node))

                # Посмотреть на R2
                menu.addSeparator()
                action = menu.addAction("☁️ Посмотреть на R2")
                action.setData(("view_on_r2", node))

                action = menu.addAction("🗄️ Показать в Supabase")
                action.setData(("view_in_supabase", node))

                menu.addSeparator()
                menu.addAction("✏️ Переименовать").setData(("rename", node))
                menu.addSeparator()
                menu.addAction("🗑️ Удалить").setData(("delete", node))
        else:
            menu.addAction("📁 Создать проект").setData(("create_project",))

        action = menu.exec_(self.tree.mapToGlobal(pos))
        if action:
            data = action.data()
            if data:
                self._handle_menu_action(data)

    def _handle_menu_action(self, data):
        """Обработать действие меню"""
        from app.tree_client import NodeStatus

        if not data:
            return

        action = data[0]
        logger.debug(f"_handle_menu_action: action={action}, data={data}")

        if action == "create_project":
            self._create_project()
        elif action == "add":
            child_type, parent_node = data[1], data[2]
            self._create_child_node(parent_node, child_type)
        elif action == "upload":
            node = data[1]
            self._upload_file(node)
        elif action == "rename":
            node = data[1]
            self._rename_node(node)
        elif action == "complete":
            node = data[1]
            self._set_status(node, NodeStatus.COMPLETED)
        elif action == "activate":
            node = data[1]
            self._set_status(node, NodeStatus.ACTIVE)
        elif action == "delete":
            node = data[1]
            self._delete_node(node)
        elif action == "remove_stamps":
            node = data[1]
            self._remove_stamps_from_document(node)
        elif action == "set_version":
            node, version = data[1], data[2]
            self._set_document_version(node, version)
        elif action == "copy_annotation":
            node = data[1]
            self._copy_annotation(node)
        elif action == "paste_annotation":
            node = data[1]
            self._paste_annotation(node)
        elif action == "open_folder":
            node = data[1]
            self._open_document_folder(node)
        elif action == "upload_annotation":
            node = data[1]
            self._upload_annotation_dialog(node)
        elif action == "detect_stamps":
            node = data[1]
            self._detect_and_assign_stamps(node)
        elif action == "view_on_r2":
            node = data[1]
            self._view_on_r2(node)
        elif action == "lock_document":
            node = data[1]
            self._lock_document(node)
        elif action == "unlock_document":
            node = data[1]
            self._unlock_document(node)
        elif action == "verify_blocks":
            node = data[1]
            self._verify_blocks(node)
        elif action == "view_in_supabase":
            node = data[1]
            self._view_in_supabase(node)
        elif action == "move_up":
            node = data[1]
            self._move_node_up(node)
        elif action == "move_down":
            node = data[1]
            self._move_node_down(node)
        elif action == "split_document":
            node = data[1]
            self._split_document(node)
        elif action == "reconcile_files":
            node = data[1]
            self._reconcile_files(node)