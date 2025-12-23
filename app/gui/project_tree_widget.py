"""Виджет дерева проектов с поддержкой Supabase"""
from __future__ import annotations

import logging
from typing import Dict, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QMenu, QLabel, QAbstractItemView, QFrame, QLineEdit, QStyledItemDelegate, QStyleOptionViewItem, QStyle
)
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QRect
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QFont


class VersionHighlightDelegate(QStyledItemDelegate):
    """Делегат для отображения версии красным цветом"""
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        version = index.data(Qt.UserRole + 1)
        if not version:
            super().paint(painter, option, index)
            return
        
        # Рисуем фон выделения
        self.initStyleOption(option, index)
        painter.save()
        
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#2a2d2e"))
        
        text = index.data(Qt.DisplayRole)
        icon_end = 2  # Позиция после иконки (эмодзи + пробел)
        
        # Разбиваем текст: иконка + остальное
        parts = text.split(" ", 1)
        icon_part = parts[0] + " " if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        
        x = option.rect.x() + 4
        y = option.rect.y()
        h = option.rect.height()
        
        fm = painter.fontMetrics()
        
        # Иконка
        painter.setPen(option.palette.text().color())
        painter.drawText(x, y, fm.horizontalAdvance(icon_part), h, Qt.AlignVCenter, icon_part)
        x += fm.horizontalAdvance(icon_part)
        
        # Версия красным
        painter.setPen(QColor("#ff4444"))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        fm_bold = painter.fontMetrics()
        version_with_space = version + "  "  # Два пробела для чёткого разделения
        painter.drawText(x, y, fm_bold.horizontalAdvance(version_with_space), h, Qt.AlignVCenter, version_with_space)
        x += fm_bold.horizontalAdvance(version_with_space)
        
        # Остальной текст
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(option.palette.text().color())
        painter.drawText(x, y, option.rect.width() - x, h, Qt.AlignVCenter, rest)
        
        painter.restore()

from app.tree_client import TreeClient, TreeNode, NodeType, NodeStatus, StageType, SectionType, FileType
from app.gui.tree_node_operations import TreeNodeOperationsMixin, NODE_ICONS, STATUS_COLORS

logger = logging.getLogger(__name__)

# Названия типов узлов для UI
NODE_TYPE_NAMES = {
    NodeType.PROJECT: "Проект",
    NodeType.STAGE: "Стадия",
    NodeType.SECTION: "Раздел",
    NodeType.TASK_FOLDER: "Папка заданий",
    NodeType.DOCUMENT: "Документ",
}

__all__ = ['ProjectTreeWidget', 'NODE_TYPE_NAMES']


class ProjectTreeWidget(TreeNodeOperationsMixin, QWidget):
    """Виджет дерева проектов"""
    
    document_selected = Signal(str, str)  # node_id, r2_key
    file_uploaded_r2 = Signal(str, str)  # node_id, r2_key
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = TreeClient()
        self._node_map: Dict[str, QTreeWidgetItem] = {}
        self._stage_types: List[StageType] = []
        self._section_types: List[SectionType] = []
        self._loading = False
        self._copied_annotation: Dict = {}  # {"json": str, "source_r2_key": str}
        self._current_document_id: str = ""  # ID текущего открытого документа
        self._auto_refresh_timer: QTimer = None
        self._last_node_count: int = 0  # Для отслеживания изменений
        self._setup_ui()
        self._setup_auto_refresh()
        
        QTimer.singleShot(100, self._initial_load)
    
    def _setup_auto_refresh(self):
        """Настроить автообновление дерева"""
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_tree)
        self._auto_refresh_timer.start(10000)  # Каждые 10 секунд
    
    def _auto_refresh_tree(self):
        """Автоматическое обновление дерева (проверка изменений)"""
        if self._loading:
            return
        
        try:
            # Быстрая проверка количества корневых узлов
            roots = self.client.get_root_nodes()
            current_count = len(roots)
            
            # Проверяем изменились ли данные
            if current_count != self._last_node_count:
                self._last_node_count = current_count
                self._refresh_tree()
                return
            
            # Проверяем обновление существующих узлов (по updated_at)
            for root in roots:
                if root.id in self._node_map:
                    item = self._node_map[root.id]
                    old_node = item.data(0, Qt.UserRole)
                    if isinstance(old_node, TreeNode):
                        if old_node.updated_at != root.updated_at:
                            self._refresh_tree()
                            return
                else:
                    # Новый узел - обновляем
                    self._refresh_tree()
                    return
                    
        except Exception as e:
            logger.debug(f"Auto-refresh check failed: {e}")
    
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
        self.tree.installEventFilter(self)
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
        
        # Делегат для красной версии
        self.tree.setItemDelegate(VersionHighlightDelegate(self.tree))
        
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
            self._last_node_count = len(roots)
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
        
        # Для документов показываем версию и иконку аннотации
        if node.node_type == NodeType.DOCUMENT:
            version_tag = f"[v{node.version}]" if node.version else "[v1]"
            has_annotation = node.attributes.get("has_annotation", False)
            ann_icon = "📋" if has_annotation else ""
            display_name = f"{icon} {node.name} {ann_icon}".strip()
            # Сохраняем версию отдельно для отображения красным
            version_display = version_tag
        elif node.code:
            display_name = f"{icon} [{node.code}] {node.name}"
            version_display = None
        else:
            display_name = f"{icon} {node.name}"
            version_display = None
        
        item = QTreeWidgetItem([display_name])
        item.setData(0, Qt.UserRole, node)
        item.setData(0, Qt.UserRole + 1, version_display)  # Версия для делегата
        item.setForeground(0, QColor(STATUS_COLORS.get(node.status, "#e0e0e0")))
        
        self._node_map[node.id] = item
        return item
    
    def _add_placeholder(self, item: QTreeWidgetItem, node: TreeNode):
        """Добавить placeholder для lazy loading"""
        allowed = node.get_allowed_child_types()
        # Для документов всегда добавляем placeholder (markdown может быть)
        if node.node_type == NodeType.DOCUMENT:
            placeholder = QTreeWidgetItem(["..."])
            placeholder.setData(0, Qt.UserRole, "placeholder")
            item.addChild(placeholder)
        elif allowed:
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
            # Для документов загружаем markdown файлы
            if parent_node.node_type == NodeType.DOCUMENT:
                self._load_document_files(parent_item, parent_node)
                return
            
            children = self.client.get_children(parent_node.id)
            for child in children:
                child_item = self._create_tree_item(child)
                parent_item.addChild(child_item)
                self._add_placeholder(child_item, child)
        except Exception as e:
            logger.error(f"Failed to load children: {e}")
    
    def _load_document_files(self, parent_item: QTreeWidgetItem, doc_node: TreeNode):
        """Загрузить файлы документа (markdown)"""
        try:
            files = self.client.get_node_files(doc_node.id, FileType.RESULT_MD)
            logger.debug(f"Document {doc_node.id}: found {len(files)} md files")
            
            if not files:
                # Fallback: проверяем R2 напрямую (markdown рядом с PDF)
                from rd_core.r2_storage import R2Storage
                from pathlib import Path, PurePosixPath
                r2 = R2Storage()
                doc_stem = Path(doc_node.name).stem
                
                # Markdown лежит рядом с PDF
                pdf_r2_key = doc_node.attributes.get("r2_key", "")
                if pdf_r2_key:
                    tree_prefix = str(PurePosixPath(pdf_r2_key).parent)
                else:
                    tree_prefix = f"tree_docs/{doc_node.id}"
                
                md_key = f"{tree_prefix}/{doc_stem}.md"
                if r2.exists(md_key):
                    from app.tree_client import NodeFile
                    virtual_file = NodeFile(
                        id="virtual",
                        node_id=doc_node.id,
                        file_type=FileType.RESULT_MD,
                        r2_key=md_key,
                        file_name=f"{doc_stem}.md"
                    )
                    files = [virtual_file]
                    logger.info(f"Found markdown in R2: {md_key}")
            
            for f in files:
                md_item = QTreeWidgetItem([f"📄 {f.file_name}"])
                md_item.setData(0, Qt.UserRole, ("markdown", doc_node, f))
                md_item.setForeground(0, QColor("#9cdcfe"))
                parent_item.addChild(md_item)
                logger.info(f"[LOAD_FILES] Added markdown item: {f.file_name}, r2_key={f.r2_key}")
        except Exception as e:
            logger.error(f"Failed to load document files: {e}", exc_info=True)
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Двойной клик - открыть документ (скачать из R2) или markdown"""
        data = item.data(0, Qt.UserRole)
        item_text = item.text(0) if item else "None"
        logger.info(f"[DBL_CLICK] item_text='{item_text}', data_type={type(data).__name__}, data={data}")
        
        # Markdown файл (Qt конвертирует tuple в list)
        if isinstance(data, (tuple, list)):
            logger.info(f"[DBL_CLICK] sequence detected, len={len(data)}, first={data[0] if data else 'empty'}")
            if len(data) >= 1 and data[0] == "markdown":
                _, doc_node, node_file = data
                logger.info(f"[DBL_CLICK] Opening markdown: {node_file.file_name}, r2_key={node_file.r2_key}")
                self._open_markdown_editor(doc_node, node_file)
                return
            else:
                logger.warning(f"[DBL_CLICK] tuple but not markdown: {data}")
        
        # Документ PDF
        if isinstance(data, TreeNode) and data.node_type == NodeType.DOCUMENT:
            r2_key = data.attributes.get("r2_key", "")
            logger.info(f"[DBL_CLICK] PDF document: {data.name}, r2_key={r2_key}")
            if r2_key:
                self.highlight_document(data.id)
                self.document_selected.emit(data.id, r2_key)
        else:
            logger.info(f"[DBL_CLICK] Not handled: data_type={type(data).__name__}")
    
    def _open_markdown_editor(self, doc_node: TreeNode, node_file):
        """Открыть редактор markdown"""
        from rd_core.r2_storage import R2Storage
        from app.gui.markdown_editor_dialog import MarkdownEditorDialog
        
        logger.info(f"[MD_EDITOR] Starting, doc={doc_node.name}, file={node_file.file_name}, r2_key={node_file.r2_key}")
        
        try:
            r2 = R2Storage()
            logger.info(f"[MD_EDITOR] Downloading from R2: {node_file.r2_key}")
            md_text = r2.download_text(node_file.r2_key) or ""
            logger.info(f"[MD_EDITOR] Downloaded {len(md_text)} chars")
            
            def save_callback(new_text: str) -> bool:
                try:
                    return r2.upload_text(new_text, node_file.r2_key)
                except Exception as e:
                    logger.error(f"Failed to save markdown: {e}")
                    return False
            
            logger.info(f"[MD_EDITOR] Creating dialog")
            dialog = MarkdownEditorDialog(
                title=f"{doc_node.name} — {node_file.file_name}",
                markdown_text=md_text,
                save_callback=save_callback,
                parent=self.window()
            )
            logger.info(f"[MD_EDITOR] Showing dialog")
            dialog.show()
            logger.info(f"[MD_EDITOR] Dialog shown")
        except Exception as e:
            logger.error(f"[MD_EDITOR] Failed to open markdown editor: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть markdown: {e}")
    
    def highlight_document(self, node_id: str):
        """Подсветить текущий открытый документ"""
        # Сбросить подсветку предыдущего
        if self._current_document_id and self._current_document_id in self._node_map:
            prev_item = self._node_map[self._current_document_id]
            prev_node = prev_item.data(0, Qt.UserRole)
            if isinstance(prev_node, TreeNode):
                prev_item.setBackground(0, QColor("transparent"))
                prev_item.setForeground(0, QColor(STATUS_COLORS.get(prev_node.status, "#e0e0e0")))
        
        # Установить подсветку нового
        self._current_document_id = node_id
        if node_id and node_id in self._node_map:
            item = self._node_map[node_id]
            item.setBackground(0, QColor("#264f78"))  # Синий фон для активного
            item.setForeground(0, QColor("#ffffff"))  # Белый текст
            self.tree.scrollToItem(item)
    
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
                    # Подменю выбора версии
                    from app.gui.folder_settings_dialog import get_max_versions
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
        elif action == "set_version":
            node, version = data[1], data[2]
            self._set_document_version(node, version)
        elif action == "copy_annotation":
            node = data[1]
            self._copy_annotation(node)
        elif action == "paste_annotation":
            node = data[1]
            self._paste_annotation(node)
    
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
    
    def eventFilter(self, obj, event):
        """Обработка событий для дерева"""
        if obj == self.tree and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Delete:
                item = self.tree.currentItem()
                if item:
                    node = item.data(0, Qt.UserRole)
                    if isinstance(node, TreeNode):
                        self._delete_node(node)
                        return True
        return super().eventFilter(obj, event)
    
    def _copy_annotation(self, node: TreeNode):
        """Скопировать аннотацию документа в буфер"""
        from rd_core.r2_storage import R2Storage
        from app.gui.file_operations import get_annotation_r2_key
        from PySide6.QtWidgets import QMessageBox
        
        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            return
        
        try:
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)
            json_content = r2.download_text(ann_r2_key)
            
            if json_content:
                self._copied_annotation = {
                    "json": json_content,
                    "source_r2_key": r2_key
                }
                self.status_label.setText(f"📋 Аннотация скопирована")
                logger.info(f"Annotation copied from {ann_r2_key}")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось загрузить аннотацию")
        except Exception as e:
            logger.error(f"Copy annotation failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка копирования: {e}")
    
    def _paste_annotation(self, node: TreeNode):
        """Вставить аннотацию из буфера в документ"""
        from rd_core.r2_storage import R2Storage
        from app.gui.file_operations import get_annotation_r2_key
        from PySide6.QtWidgets import QMessageBox
        
        if not self._copied_annotation:
            return
        
        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            return
        
        try:
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)
            
            # Загружаем скопированную аннотацию
            if r2.upload_text(self._copied_annotation["json"], ann_r2_key):
                # Обновляем флаг has_annotation
                attrs = node.attributes.copy()
                attrs["has_annotation"] = True
                self.client.update_node(node.id, attributes=attrs)
                
                # Обновляем отображение
                item = self._node_map.get(node.id)
                if item:
                    node.attributes = attrs
                    item.setData(0, Qt.UserRole, node)  # Обновляем данные узла
                    icon = NODE_ICONS.get(node.node_type, "📄")
                    version_tag = f"[v{node.version}]" if node.version else "[v1]"
                    display_name = f"{icon} {node.name} 📋".strip()
                    item.setText(0, display_name)
                    item.setData(0, Qt.UserRole + 1, version_tag)
                
                self.status_label.setText(f"📥 Аннотация вставлена")
                logger.info(f"Annotation pasted to {ann_r2_key}")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось сохранить аннотацию")
        except Exception as e:
            logger.error(f"Paste annotation failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка вставки: {e}")
