"""Виджет дерева проектов с поддержкой Supabase"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QMenu, QInputDialog, QMessageBox, QFileDialog, QLabel, QDialog, QFormLayout,
    QComboBox, QLineEdit, QDialogButtonBox, QAbstractItemView, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QIcon

from app.tree_client import TreeClient, TreeNode, NodeType, NodeStatus, StageType, SectionType

logger = logging.getLogger(__name__)

# Иконки для типов узлов
NODE_ICONS = {
    NodeType.PROJECT: "📁",
    NodeType.STAGE: "🏗",
    NodeType.SECTION: "📚",
    NodeType.TASK_FOLDER: "📂",
    NodeType.DOCUMENT: "📄",
}

NODE_TYPE_NAMES = {
    NodeType.PROJECT: "Проект",
    NodeType.STAGE: "Стадия",
    NodeType.SECTION: "Раздел",
    NodeType.TASK_FOLDER: "Папка заданий",
    NodeType.DOCUMENT: "Документ",
}

STATUS_COLORS = {
    NodeStatus.ACTIVE: "#e0e0e0",
    NodeStatus.COMPLETED: "#4caf50",
    NodeStatus.ARCHIVED: "#9e9e9e",
}


class CreateNodeDialog(QDialog):
    """Диалог создания узла дерева"""
    
    def __init__(
        self,
        parent,
        node_type: NodeType,
        stage_types: List[StageType] = None,
        section_types: List[SectionType] = None,
    ):
        super().__init__(parent)
        self.node_type = node_type
        self.stage_types = stage_types or []
        self.section_types = section_types or []
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWindowTitle(f"Создать: {NODE_TYPE_NAMES[self.node_type]}")
        self.setMinimumWidth(350)
        
        layout = QFormLayout(self)
        
        if self.node_type == NodeType.STAGE and self.stage_types:
            self.stage_combo = QComboBox()
            for st in self.stage_types:
                self.stage_combo.addItem(f"{st.code} - {st.name}", st)
            layout.addRow("Стадия:", self.stage_combo)
            self.name_edit = None
        elif self.node_type == NodeType.SECTION and self.section_types:
            self.section_combo = QComboBox()
            for st in self.section_types:
                self.section_combo.addItem(f"{st.code} - {st.name}", st)
            layout.addRow("Раздел:", self.section_combo)
            self.name_edit = None
        else:
            self.name_edit = QLineEdit()
            self.name_edit.setPlaceholderText("Введите название...")
            layout.addRow("Название:", self.name_edit)
            self.stage_combo = None
            self.section_combo = None
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def get_data(self) -> tuple[str, Optional[str]]:
        """Вернуть (name, code)"""
        if self.node_type == NodeType.STAGE and hasattr(self, 'stage_combo') and self.stage_combo is not None:
            st = self.stage_combo.currentData()
            if st and hasattr(st, 'name') and hasattr(st, 'code'):
                return st.name, st.code
            # Fallback если данные потерялись
            text = self.stage_combo.currentText()
            if " - " in text:
                code, name = text.split(" - ", 1)
                return name, code
            return text, None
        elif self.node_type == NodeType.SECTION and hasattr(self, 'section_combo') and self.section_combo is not None:
            st = self.section_combo.currentData()
            if st and hasattr(st, 'name') and hasattr(st, 'code'):
                return st.name, st.code
            # Fallback если данные потерялись
            text = self.section_combo.currentText()
            if " - " in text:
                code, name = text.split(" - ", 1)
                return name, code
            return text, None
        else:
            return self.name_edit.text().strip(), None


class ProjectTreeWidget(QWidget):
    """Виджет дерева проектов"""
    
    document_selected = Signal(str, str)  # node_id, r2_key
    file_uploaded = Signal(str)  # local_path - сигнал для открытия файла в редакторе
    refresh_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = TreeClient()
        self._node_map: Dict[str, QTreeWidgetItem] = {}
        self._stage_types: List[StageType] = []
        self._section_types: List[SectionType] = []
        self._loading = False
        self._setup_ui()
        
        # Отложенная загрузка
        QTimer.singleShot(100, self._initial_load)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Заголовок
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
                padding: 6px 12px;
                border-radius: 2px;
            }
            QPushButton:hover { background-color: #1177bb; }
        """)
        self.create_btn.clicked.connect(self._create_project)
        
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setToolTip("Обновить")
        self.refresh_btn.setFixedSize(32, 32)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                border-radius: 2px;
            }
            QPushButton:hover { background-color: #4e4e52; }
        """)
        self.refresh_btn.clicked.connect(self._refresh_tree)
        
        icon_btn_style = """
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                border-radius: 2px;
            }
            QPushButton:hover { background-color: #4e4e52; }
        """
        
        self.expand_all_btn = QPushButton("⊞")
        self.expand_all_btn.setCursor(Qt.PointingHandCursor)
        self.expand_all_btn.setToolTip("Развернуть все")
        self.expand_all_btn.setFixedSize(32, 32)
        self.expand_all_btn.setStyleSheet(icon_btn_style)
        self.expand_all_btn.clicked.connect(self._expand_all)
        
        self.collapse_all_btn = QPushButton("⊟")
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
        
        # Поле поиска
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
        
        # Дерево
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
        
        # Статус
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
                
                # Добавить дочерний элемент (кроме документов)
                for child_type in allowed:
                    if child_type == NodeType.DOCUMENT:
                        continue  # Документы добавляются через загрузку файла
                    icon = NODE_ICONS.get(child_type, "+")
                    action = menu.addAction(f"{icon} Добавить {NODE_TYPE_NAMES[child_type]}")
                    action.setData(("add", child_type, node))
                
                # Если это папка заданий - добавить файл
                if node.node_type == NodeType.TASK_FOLDER:
                    action = menu.addAction("📄 Добавить файл")
                    action.setData(("upload", node))
                
                menu.addSeparator()
                
                # Редактирование
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
            logger.debug(f"add action: child_type={child_type} (type={type(child_type)}), parent_node={parent_node}")
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
    
    def _create_project(self):
        """Создать новый проект"""
        name, ok = QInputDialog.getText(self, "Новый проект", "Название проекта:")
        if ok and name.strip():
            try:
                node = self.client.create_node(NodeType.PROJECT, name.strip())
                item = self._create_tree_item(node)
                self.tree.addTopLevelItem(item)
                self._add_placeholder(item, node)
                self.tree.setCurrentItem(item)
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def _create_child_node(self, parent_node: TreeNode, child_type):
        """Создать дочерний узел"""
        # Конвертируем строку в NodeType если нужно
        if isinstance(child_type, str):
            logger.debug(f"child_type is str: {child_type}, converting to NodeType")
            child_type = NodeType(child_type)
        
        logger.debug(f"_create_child_node: parent={parent_node.id}, child_type={child_type}")
        
        stage_types = self._stage_types if child_type == NodeType.STAGE else None
        section_types = self._section_types if child_type == NodeType.SECTION else None
        
        logger.debug(f"stage_types count: {len(stage_types) if stage_types else 0}")
        logger.debug(f"section_types count: {len(section_types) if section_types else 0}")
        
        dialog = CreateNodeDialog(self, child_type, stage_types, section_types)
        if dialog.exec_() == QDialog.Accepted:
            name, code = dialog.get_data()
            logger.debug(f"Dialog result: name={name}, code={code}")
            if name:
                try:
                    logger.debug(f"Creating node: type={child_type}, name={name}, parent={parent_node.id}, code={code}")
                    node = self.client.create_node(child_type, name, parent_node.id, code)
                    logger.debug(f"Node created: {node.id}")
                    parent_item = self._node_map.get(parent_node.id)
                    if parent_item:
                        # Удаляем placeholder если есть
                        if parent_item.childCount() == 1:
                            child = parent_item.child(0)
                            if child.data(0, Qt.UserRole) == "placeholder":
                                parent_item.removeChild(child)
                        
                        child_item = self._create_tree_item(node)
                        parent_item.addChild(child_item)
                        self._add_placeholder(child_item, node)
                        parent_item.setExpanded(True)
                        self.tree.setCurrentItem(child_item)
                except Exception as e:
                    logger.exception(f"Error creating child node: {e}")
                    QMessageBox.critical(self, "Ошибка", str(e))
    
    def _upload_file(self, node: TreeNode):
        """Добавить файл в папку заданий (копирует локально)"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if not paths:
            return
        
        from pathlib import Path
        import shutil
        from app.gui.folder_settings_dialog import get_projects_dir
        
        projects_dir = get_projects_dir()
        if not projects_dir or not Path(projects_dir).exists():
            QMessageBox.warning(self, "Ошибка", "Папка проектов не задана в настройках")
            return
        
        parent_item = self._node_map.get(node.id)
        
        for path in paths:
            file_path = Path(path)
            filename = file_path.name
            file_size = file_path.stat().st_size
            
            # Создаём папку для документа: projects_dir/{node_name}/
            doc_folder = Path(projects_dir) / node.name
            doc_folder.mkdir(parents=True, exist_ok=True)
            
            # Копируем файл
            local_path = doc_folder / filename
            try:
                shutil.copy2(file_path, local_path)
                logger.info(f"File copied to: {local_path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось скопировать файл:\n{e}")
                continue
            
            # Добавляем документ в дерево
            try:
                doc_node = self.client.add_document(
                    parent_id=node.id,
                    name=filename,
                    r2_key="",
                    file_size=file_size,
                    local_path=str(local_path)
                )
                
                # Добавляем в UI
                if parent_item:
                    # Удаляем placeholder если есть
                    if parent_item.childCount() == 1:
                        child = parent_item.child(0)
                        if child.data(0, Qt.UserRole) == "placeholder":
                            parent_item.removeChild(child)
                    
                    child_item = self._create_tree_item(doc_node)
                    parent_item.addChild(child_item)
                    parent_item.setExpanded(True)
                
                logger.info(f"Document added: {doc_node.id}")
                
                # Открыть файл в редакторе
                self.file_uploaded.emit(str(local_path))
                
            except Exception as e:
                logger.exception(f"Failed to add document: {e}")
                QMessageBox.critical(self, "Ошибка", f"Файл скопирован, но не добавлен в дерево:\n{e}")
    
    def _rename_node(self, node: TreeNode):
        """Переименовать узел"""
        new_name, ok = QInputDialog.getText(
            self, "Переименовать", "Новое название:", text=node.name
        )
        if ok and new_name.strip() and new_name.strip() != node.name:
            try:
                self.client.update_node(node.id, name=new_name.strip())
                item = self._node_map.get(node.id)
                if item:
                    icon = NODE_ICONS.get(node.node_type, "📄")
                    code_part = f"[{node.code}] " if node.code else ""
                    item.setText(0, f"{icon} {code_part}{new_name.strip()}")
                    node.name = new_name.strip()
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
    
    def _delete_node(self, node: TreeNode):
        """Удалить узел"""
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить '{node.name}' и все вложенные элементы?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                if self.client.delete_node(node.id):
                    item = self._node_map.get(node.id)
                    if item:
                        parent = item.parent()
                        if parent:
                            parent.removeChild(item)
                        else:
                            idx = self.tree.indexOfTopLevelItem(item)
                            self.tree.takeTopLevelItem(idx)
                        del self._node_map[node.id]
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def _filter_tree(self, text: str):
        """Фильтровать дерево по тексту"""
        text = text.lower().strip()
        
        if not text:
            # Показать все элементы
            self._show_all_items()
            return
        
        # Скрыть все, затем показать только совпадающие
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
        """
        Фильтровать элемент и его детей.
        Возвращает True если элемент или его дети содержат текст.
        parent_matches=True означает что родитель совпал - показываем всех потомков.
        """
        node = item.data(0, Qt.UserRole)
        if node == "placeholder":
            item.setHidden(True)
            return False
        
        # Проверяем текущий элемент
        item_text = item.text(0).lower()
        matches = text in item_text
        
        # Загружаем детей для поиска в глубину (если placeholder)
        if isinstance(node, TreeNode):
            self._ensure_children_loaded(item, node)
        
        # Если родитель совпал - показываем этот элемент и всех его потомков
        if parent_matches:
            item.setHidden(False)
            item.setExpanded(True)
            for i in range(item.childCount()):
                self._filter_item(item.child(i), text, parent_matches=True)
            return True
        
        # Проверяем детей (передаём parent_matches=True если текущий совпал)
        has_matching_child = False
        for i in range(item.childCount()):
            child = item.child(i)
            if self._filter_item(child, text, parent_matches=matches):
                has_matching_child = True
        
        # Показываем если есть совпадение или есть совпадающие дети
        should_show = matches or has_matching_child
        item.setHidden(not should_show)
        
        # Раскрываем если элемент совпадает или есть совпадающие дети
        if should_show and item.childCount() > 0:
            item.setExpanded(True)
        
        return should_show
    
    def _ensure_children_loaded(self, item: QTreeWidgetItem, node: TreeNode):
        """Загрузить детей если они еще не загружены (placeholder)"""
        if item.childCount() == 1:
            child = item.child(0)
            if child.data(0, Qt.UserRole) == "placeholder":
                item.removeChild(child)
                self._load_children(item, node)

