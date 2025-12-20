"""Виджет дерева проектов с поддержкой Supabase"""
from __future__ import annotations

import logging
from typing import Dict, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QMenu, QLabel, QAbstractItemView, QFrame, QLineEdit
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor

from app.tree_client import TreeClient, TreeNode, NodeType, NodeStatus, StageType, SectionType
from app.gui.tree_node_operations import TreeNodeOperationsMixin, NODE_ICONS, STATUS_COLORS

logger = logging.getLogger(__name__)

NODE_TYPE_NAMES = {
    NodeType.PROJECT: "Проект",
    NodeType.STAGE: "Стадия",
    NodeType.SECTION: "Раздел",
    NodeType.TASK_FOLDER: "Папка заданий",
    NodeType.DOCUMENT: "Документ",
}


class ProjectTreeWidget(TreeNodeOperationsMixin, QWidget):
    """Виджет дерева проектов"""
    
    document_selected = Signal(str, str)
    file_uploaded = Signal(str)
    refresh_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = TreeClient()
        self._node_map: Dict[str, QTreeWidgetItem] = {}
        self._stage_types: List[StageType] = []
        self._section_types: List[SectionType] = []
        self._loading = False
        self._setup_ui()
        
        QTimer.singleShot(100, self._initial_load)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QWidget()
        header.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3e3e42;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(10)
        
        title_label = QLabel("ДЕРЕВО ПРОЕКТОВ")
        title_label.setStyleSheet("color: #bbbbbb; font-weight: bold; font-size: 9pt;")
        header_layout.addWidget(title_label)
        
        btns_layout = QHBoxLayout()
        btns_layout.setSpacing(8)
        
        self.create_btn = QPushButton("+ Проект")
        self.create_btn.setCursor(Qt.PointingHandCursor)
        self.create_btn.setStyleSheet("""
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover { 
                background-color: #1177bb;
            }
            QPushButton:pressed {
                background-color: #0a4d78;
            }
        """)
        self.create_btn.clicked.connect(self._create_project)
        
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setToolTip("Обновить")
        self.refresh_btn.setFixedSize(32, 32)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: #cccccc;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { 
                background-color: #505054;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #0e639c;
            }
        """)
        self.refresh_btn.clicked.connect(self._refresh_tree)
        
        icon_btn_style = """
            QPushButton {
                background-color: #3e3e42;
                color: #cccccc;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { 
                background-color: #505054;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #0e639c;
            }
        """
        
        self.expand_all_btn = QPushButton("▼")
        self.expand_all_btn.setCursor(Qt.PointingHandCursor)
        self.expand_all_btn.setToolTip("Развернуть все")
        self.expand_all_btn.setFixedSize(32, 32)
        self.expand_all_btn.setStyleSheet(icon_btn_style)
        self.expand_all_btn.clicked.connect(self._expand_all)
        
        self.collapse_all_btn = QPushButton("▲")
        self.collapse_all_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_all_btn.setToolTip("Свернуть все")
        self.collapse_all_btn.setFixedSize(32, 32)
        self.collapse_all_btn.setStyleSheet(icon_btn_style)
        self.collapse_all_btn.clicked.connect(self._collapse_all)
        
        btns_layout.addWidget(self.create_btn)
        btns_layout.addWidget(self.refresh_btn)
        btns_layout.addWidget(self.expand_all_btn)
        btns_layout.addWidget(self.collapse_all_btn)
        header_layout.addLayout(btns_layout)
        
        layout.addWidget(header)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: #e0e0e0;
                border: 1px solid #555;
                padding: 6px;
                border-radius: 2px;
            }
            QLineEdit:focus {
                border: 1px solid #0e639c;
            }
        """)
        self.search_input.textChanged.connect(self._filter_tree)
        layout.addWidget(self.search_input)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFrameShape(QFrame.NoFrame)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setDefaultDropAction(Qt.MoveAction)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #1e1e1e;
                color: #e0e0e0;
                outline: none;
                border: none;
            }
            QTreeWidget::item {
                padding: 4px;
                border-radius: 2px;
            }
            QTreeWidget::item:hover {
                background-color: #2a2d2e;
            }
            QTreeWidget::item:selected {
                background-color: #094771;
            }
        """)
        
        layout.addWidget(self.tree)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 8pt; padding: 4px;")
        layout.addWidget(self.status_label)
    
    def _initial_load(self):
        """Начальная загрузка"""
        if not self.client.is_available():
            self.status_label.setText("⚠ Supabase недоступен")
            return
        
        try:
            self._stage_types = self.client.get_stage_types()
            self._section_types = self.client.get_section_types()
        except Exception as e:
            logger.error(f"Failed to load types: {e}")
        
        self._refresh_tree()
    
    def _expand_all(self):
        """Развернуть все элементы"""
        self.tree.expandAll()
    
    def _collapse_all(self):
        """Свернуть все элементы"""
        self.tree.collapseAll()
    
    def _refresh_tree(self):
        """Обновить дерево"""
        if self._loading:
            return
        
        self._loading = True
        self.status_label.setText("Загрузка...")
        self.tree.clear()
        self._node_map.clear()
        
        try:
            roots = self.client.get_root_nodes()
            for node in roots:
                item = self._create_tree_item(node)
                self.tree.addTopLevelItem(item)
                self._add_placeholder(item, node)
            
            self.status_label.setText(f"Проектов: {len(roots)}")
        except Exception as e:
            logger.error(f"Failed to refresh tree: {e}")
            self.status_label.setText(f"Ошибка: {e}")
        finally:
            self._loading = False
    
    def _create_tree_item(self, node: TreeNode) -> QTreeWidgetItem:
        """Создать элемент дерева"""
        icon = NODE_ICONS.get(node.node_type, "📄")
        display_name = f"{icon} {node.name}"
        if node.code:
            display_name = f"{icon} [{node.code}] {node.name}"
        
        item = QTreeWidgetItem([display_name])
        item.setData(0, Qt.UserRole, node)
        item.setForeground(0, QColor(STATUS_COLORS.get(node.status, "#e0e0e0")))
        
        self._node_map[node.id] = item
        return item
    
    def _add_placeholder(self, item: QTreeWidgetItem, node: TreeNode):
        """Добавить placeholder для lazy loading"""
        allowed = node.get_allowed_child_types()
        if allowed:
            placeholder = QTreeWidgetItem(["..."])
            placeholder.setData(0, Qt.UserRole, "placeholder")
            item.addChild(placeholder)
    
    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Lazy loading при раскрытии"""
        if item.childCount() == 1:
            child = item.child(0)
            if child.data(0, Qt.UserRole) == "placeholder":
                node = item.data(0, Qt.UserRole)
                if isinstance(node, TreeNode):
                    item.removeChild(child)
                    self._load_children(item, node)
    
    def _load_children(self, parent_item: QTreeWidgetItem, parent_node: TreeNode):
        """Загрузить дочерние узлы"""
        try:
            children = self.client.get_children(parent_node.id)
            for child in children:
                child_item = self._create_tree_item(child)
                parent_item.addChild(child_item)
                self._add_placeholder(child_item, child)
        except Exception as e:
            logger.error(f"Failed to load children: {e}")
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Двойной клик - открыть документ"""
        node = item.data(0, Qt.UserRole)
        if isinstance(node, TreeNode) and node.node_type == NodeType.DOCUMENT:
            local_path = node.attributes.get("local_path", "")
            if local_path:
                from pathlib import Path
                if Path(local_path).exists():
                    self.file_uploaded.emit(local_path)
                    return
            r2_key = node.attributes.get("r2_key", "")
            if r2_key:
                self.document_selected.emit(node.id, r2_key)
    
    def _show_context_menu(self, pos):
        """Показать контекстное меню"""
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
                    local_path = node.attributes.get("local_path", "")
                    if local_path and local_path.lower().endswith(".pdf"):
                        action = menu.addAction("🗑️ Удалить рамки/QR")
                        action.setData(("remove_stamps", node))
                
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
        if item.childCount() == 1:
            child = item.child(0)
            if child.data(0, Qt.UserRole) == "placeholder":
                item.removeChild(child)
                self._load_children(item, node)
