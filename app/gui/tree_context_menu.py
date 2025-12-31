"""Миксин для контекстного меню дерева проектов"""
import logging

from PySide6.QtWidgets import QMenu
from PySide6.QtCore import Qt

from app.tree_client import TreeNode, NodeType

logger = logging.getLogger(__name__)


class TreeContextMenuMixin:
    """Миксин для контекстного меню дерева"""
    
    def _show_context_menu(self, pos):
        """Показать контекстное меню"""
        from app.gui.tree_node_operations import NODE_ICONS
        from app.gui.folder_settings_dialog import get_max_versions
        
        # Названия типов узлов для UI
        NODE_TYPE_NAMES = {
            NodeType.PROJECT: "Проект",
            NodeType.STAGE: "Стадия",
            NodeType.SECTION: "Раздел",
            NodeType.TASK_FOLDER: "Папка заданий",
            NodeType.DOCUMENT: "Документ",
        }
        
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        
        if item:
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode):
                allowed = node.get_allowed_child_types()
                
                for child_type in allowed:
                    if child_type == NodeType.DOCUMENT:
                        continue
                    icon = NODE_ICONS.get(child_type, "+")
                    action = menu.addAction(f"{icon} Добавить {NODE_TYPE_NAMES[child_type]}")
                    action.setData(("add", child_type, node))
                
                if node.node_type == NodeType.TASK_FOLDER:
                    action = menu.addAction("📄 Добавить файл")
                    action.setData(("upload", node))
                
                if node.node_type == NodeType.DOCUMENT:
                    # Открыть папку с файлами
                    action = menu.addAction("📂 Открыть папку")
                    action.setData(("open_folder", node))
                    
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
                
                # Посмотреть на R2
                menu.addSeparator()
                action = menu.addAction("☁️ Посмотреть на R2")
                action.setData(("view_on_r2", node))
                
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


