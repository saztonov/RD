"""Виджет дерева проектов с поддержкой Supabase"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QMenu, QLabel, QAbstractItemView, QFrame, QLineEdit, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QSettings
from PySide6.QtGui import QColor

from app.tree_client import TreeClient, TreeNode, NodeType, NodeStatus, StageType, SectionType, FileType, FileType
from app.gui.tree_node_operations import TreeNodeOperationsMixin, NODE_ICONS, STATUS_COLORS
from app.gui.tree_delegates import VersionHighlightDelegate
from app.gui.tree_sync_mixin import TreeSyncMixin, SYNC_ICONS
from app.gui.tree_filter_mixin import TreeFilterMixin
from app.gui.tree_context_menu import TreeContextMenuMixin
from app.gui.sync_check_worker import SyncCheckWorker, SyncStatus
from rd_core.pdf_status import PDFStatus

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


class ProjectTreeWidget(
    TreeNodeOperationsMixin,
    TreeSyncMixin,
    TreeFilterMixin,
    TreeContextMenuMixin,
    QWidget
):
    """Виджет дерева проектов"""
    
    document_selected = Signal(str, str)  # node_id, r2_key
    file_uploaded_r2 = Signal(str, str)  # node_id, r2_key
    annotation_replaced = Signal(str)  # r2_key - для обновления открытого документа
    
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
        self._sync_statuses: Dict[str, SyncStatus] = {}  # node_id -> SyncStatus
        self._sync_worker: SyncCheckWorker = None
        self._expanded_nodes: set = set()  # Множество ID раскрытых узлов
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
        
        self.sync_check_btn = QPushButton("🔄")
        self.sync_check_btn.setCursor(Qt.PointingHandCursor)
        self.sync_check_btn.setToolTip("Проверить синхронизацию с R2")
        self.sync_check_btn.setFixedSize(32, 32)
        self.sync_check_btn.setStyleSheet(icon_btn_style)
        self.sync_check_btn.clicked.connect(self._start_sync_check)
        
        btns_layout.addWidget(self.create_btn)
        btns_layout.addWidget(self.refresh_btn)
        btns_layout.addWidget(self.expand_all_btn)
        btns_layout.addWidget(self.collapse_all_btn)
        btns_layout.addWidget(self.sync_check_btn)
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
        self.tree.setDragEnabled(False)
        self.tree.setAcceptDrops(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemCollapsed.connect(self._on_item_collapsed)
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
        
        self._load_expanded_state()
        self.refresh_types()
        self._refresh_tree()
    
    def refresh_types(self):
        """Обновить кэшированные типы стадий и разделов"""
        try:
            self._stage_types = self.client.get_stage_types()
            self._section_types = self.client.get_section_types()
            logger.debug(f"Refreshed types: {len(self._stage_types)} stages, {len(self._section_types)} sections")
        except Exception as e:
            logger.error(f"Failed to load types: {e}")
    
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
        self._sync_statuses.clear()
        
        try:
            roots = self.client.get_root_nodes()
            self._last_node_count = len(roots)
            for node in roots:
                item = self._create_tree_item(node)
                self.tree.addTopLevelItem(item)
                self._add_placeholder(item, node)
            
            self.status_label.setText(f"Проектов: {len(roots)}")
            
            # Восстанавливаем раскрытое состояние с задержкой
            QTimer.singleShot(100, self._restore_expanded_state)
            
            # Запускаем проверку синхронизации с задержкой
            QTimer.singleShot(500, self._start_sync_check)
        except Exception as e:
            logger.error(f"Failed to refresh tree: {e}")
            self.status_label.setText(f"Ошибка: {e}")
        finally:
            self._loading = False
    
    def _create_tree_item(self, node: TreeNode) -> QTreeWidgetItem:
        """Создать элемент дерева"""
        icon = NODE_ICONS.get(node.node_type, "📄")
        
        # Для документов показываем версию и иконку статуса PDF из БД
        if node.node_type == NodeType.DOCUMENT:
            version_tag = f"[v{node.version}]" if node.version else "[v1]"
            # Иконка статуса PDF из БД
            status_icon = self._get_pdf_status_icon(node.pdf_status or "unknown")
            # Иконка замка для заблокированных документов
            lock_icon = "🔒" if node.is_locked else ""
            display_name = f"{icon} {node.name} {lock_icon} {status_icon}".strip()
            # Сохраняем версию отдельно для отображения красным
            version_display = version_tag
        elif node.node_type == NodeType.TASK_FOLDER:
            # Иконка синхронизации для папок заданий
            sync_status = self._sync_statuses.get(node.id, SyncStatus.UNKNOWN)
            sync_icon = SYNC_ICONS.get(sync_status, "")
            if node.code:
                display_name = f"{icon} [{node.code}] {node.name} {sync_icon}".strip()
            else:
                display_name = f"{icon} {node.name} {sync_icon}".strip()
            version_display = None
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
        
        # Устанавливаем tooltip для PDF документов
        if node.node_type == NodeType.DOCUMENT and node.pdf_status_message:
            item.setToolTip(0, node.pdf_status_message)
        
        self._node_map[node.id] = item
        return item
    
    def _get_pdf_status_icon(self, status: str) -> str:
        """Получить иконку для статуса PDF"""
        icons = {
            "complete": "✅",
            "missing_files": "⚠️",
            "missing_blocks": "❌",
            "unknown": "",
        }
        return icons.get(status, "")
    
    def _add_placeholder(self, item: QTreeWidgetItem, node: TreeNode):
        """Добавить placeholder для lazy loading"""
        allowed = node.get_allowed_child_types()
        # Для документов добавляем placeholder для файлов (crops, annotation, etc.)
        if node.node_type == NodeType.DOCUMENT:
            placeholder = QTreeWidgetItem(["📎 Файлы..."])
            placeholder.setData(0, Qt.UserRole, "files_placeholder")
            item.addChild(placeholder)
        elif allowed:
            placeholder = QTreeWidgetItem(["..."])
            placeholder.setData(0, Qt.UserRole, "placeholder")
            item.addChild(placeholder)
    
    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Lazy loading при раскрытии"""
        node = item.data(0, Qt.UserRole)
        if isinstance(node, TreeNode):
            # Сохраняем ID раскрытого узла
            self._expanded_nodes.add(node.id)
            self._save_expanded_state()
            
        if item.childCount() == 1:
            child = item.child(0)
            child_data = child.data(0, Qt.UserRole)
            if child_data == "placeholder":
                if isinstance(node, TreeNode):
                    item.removeChild(child)
                    self._load_children(item, node)
                    # Запускаем проверку синхронизации для загруженных дочерних
                    QTimer.singleShot(100, self._start_sync_check)
            elif child_data == "files_placeholder":
                if isinstance(node, TreeNode):
                    item.removeChild(child)
                    self._load_node_files(item, node)
    
    def _on_item_collapsed(self, item: QTreeWidgetItem):
        """Обработчик сворачивания узла"""
        node = item.data(0, Qt.UserRole)
        if isinstance(node, TreeNode):
            # Удаляем ID свернутого узла
            self._expanded_nodes.discard(node.id)
            self._save_expanded_state()
    
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
    
    def _load_node_files(self, parent_item: QTreeWidgetItem, node: TreeNode):
        """Загрузить список файлов документа из node_files"""
        FILE_TYPE_ICONS = {
            FileType.PDF: "📕",
            FileType.ANNOTATION: "📋",
            FileType.OCR_HTML: "🌐",
            FileType.RESULT_JSON: "📊",
            FileType.RESULT_MD: "📝",
            FileType.RESULT_ZIP: "📦",
            FileType.CROP: "✂️",
            FileType.IMAGE: "🖼️",
        }
        
        FILE_TYPE_NAMES = {
            FileType.PDF: "PDF",
            FileType.ANNOTATION: "Аннотация",
            FileType.OCR_HTML: "OCR HTML",
            FileType.RESULT_JSON: "Результат JSON",
            FileType.RESULT_MD: "Markdown",
            FileType.RESULT_ZIP: "ZIP-архив",
            FileType.CROP: "Кроп",
            FileType.IMAGE: "Изображение",
        }
        
        try:
            node_files = self.client.get_node_files(node.id)
            
            # Исключаем PDF (он уже отображается как родительский узел)
            node_files = [f for f in node_files if f.file_type != FileType.PDF]
            
            if not node_files:
                no_files_item = QTreeWidgetItem(["(нет файлов)"])
                no_files_item.setData(0, Qt.UserRole, "no_files")
                no_files_item.setForeground(0, QColor("#666666"))
                parent_item.addChild(no_files_item)
                return
            
            # Группируем кропы
            crops = [f for f in node_files if f.file_type == FileType.CROP]
            other_files = [f for f in node_files if f.file_type != FileType.CROP]
            
            # Добавляем основные файлы
            for nf in other_files:
                icon = FILE_TYPE_ICONS.get(nf.file_type, "📄")
                type_name = FILE_TYPE_NAMES.get(nf.file_type, nf.file_type.value)
                size_kb = nf.file_size // 1024 if nf.file_size else 0
                display = f"{icon} {type_name}: {nf.file_name} ({size_kb} KB)"
                
                file_item = QTreeWidgetItem([display])
                file_item.setData(0, Qt.UserRole, ("node_file", nf))
                file_item.setForeground(0, QColor("#aaaaaa"))
                parent_item.addChild(file_item)
            
            # Добавляем кропы как группу
            if crops:
                crops_display = f"✂️ Кропы ({len(crops)})"
                crops_item = QTreeWidgetItem([crops_display])
                crops_item.setData(0, Qt.UserRole, "crops_group")
                crops_item.setForeground(0, QColor("#aaaaaa"))
                parent_item.addChild(crops_item)
                
                # Добавляем каждый кроп как дочерний
                for crop in crops:
                    size_kb = crop.file_size // 1024 if crop.file_size else 0
                    crop_display = f"📄 {crop.file_name} ({size_kb} KB)"
                    crop_item = QTreeWidgetItem([crop_display])
                    crop_item.setData(0, Qt.UserRole, ("node_file", crop))
                    crop_item.setForeground(0, QColor("#888888"))
                    crops_item.addChild(crop_item)
                    
        except Exception as e:
            logger.error(f"Failed to load node files: {e}")
            error_item = QTreeWidgetItem([f"Ошибка загрузки: {e}"])
            error_item.setForeground(0, QColor("#ff4444"))
            parent_item.addChild(error_item)
    
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Двойной клик - открыть документ (скачать из R2)"""
        data = item.data(0, Qt.UserRole)
        
        # Документ PDF
        if isinstance(data, TreeNode) and data.node_type == NodeType.DOCUMENT:
            r2_key = data.attributes.get("r2_key", "")
            if r2_key:
                self.highlight_document(data.id)
                self.document_selected.emit(data.id, r2_key)
    
    
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
        # Копирование разрешено для заблокированных документов
        from rd_core.r2_storage import R2Storage
        from app.gui.file_operations import get_annotation_r2_key
        
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
        # Проверка блокировки документа
        if self._check_document_locked(node):
            return
        
        from rd_core.r2_storage import R2Storage
        from app.gui.file_operations import get_annotation_r2_key
        
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
                
                # Обновляем статус PDF и дерево
                from rd_core.pdf_status import calculate_pdf_status, PDFStatus
                from rd_core.r2_storage import R2Storage
                
                r2 = R2Storage()
                status, message = calculate_pdf_status(r2, node.id, r2_key)
                self.client.update_pdf_status(node.id, status.value, message)
                
                self.status_label.setText(f"📥 Аннотация вставлена")
                QTimer.singleShot(100, self._refresh_tree)
                logger.info(f"Annotation pasted to {ann_r2_key}")
                
                # Сигнал для обновления открытого документа
                self.annotation_replaced.emit(r2_key)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось сохранить аннотацию")
        except Exception as e:
            logger.error(f"Paste annotation failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка вставки: {e}")
    
    def _detect_and_assign_stamps(self, node: TreeNode):
        """Определить и назначить штамп на всех страницах PDF"""
        # Проверка блокировки документа
        if self._check_document_locked(node):
            return
        
        from rd_core.r2_storage import R2Storage
        from rd_core.models import Document, BlockType
        from rd_core.annotation_io import AnnotationIO
        from app.gui.file_operations import get_annotation_r2_key
        
        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            QMessageBox.warning(self, "Ошибка", "Документ не имеет привязки к R2")
            return
        
        try:
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)
            
            # Загрузить аннотацию из R2
            json_content = r2.download_text(ann_r2_key)
            if not json_content:
                QMessageBox.warning(self, "Ошибка", "Аннотация документа не найдена")
                return
            
            import json as json_module
            data = json_module.loads(json_content)
            doc, _ = Document.from_dict(data)
            
            # Получить категорию stamp из базы
            stamp_category = self.client.get_image_category_by_code("stamp")
            stamp_category_id = stamp_category.get("id") if stamp_category else None
            
            modified_count = 0
            
            # Пройтись по всем страницам
            for page in doc.pages:
                if not page.blocks:
                    continue
                
                # Пропускаем страницы, где уже есть штамп
                has_stamp = any(getattr(b, 'category_code', None) == 'stamp' for b in page.blocks)
                if has_stamp:
                    continue
                
                # Найти блок в правом нижнем углу
                # Критерий: центр блока в правом нижнем квадранте (x > 0.5, y > 0.7)
                # и максимально близок к углу (1, 1)
                best_block = None
                best_score = -1
                
                for block in page.blocks:
                    x1, y1, x2, y2 = block.coords_norm
                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2
                    
                    # Проверяем что блок в правом нижнем углу
                    if cx > 0.5 and cy > 0.7:
                        # Score = близость к правому нижнему углу
                        score = cx + cy
                        if score > best_score:
                            best_score = score
                            best_block = block
                
                # Назначить штамп
                if best_block:
                    best_block.block_type = BlockType.IMAGE
                    best_block.category_code = "stamp"
                    if stamp_category_id:
                        best_block.category_id = stamp_category_id
                    modified_count += 1
            
            if modified_count == 0:
                QMessageBox.information(self, "Результат", "Штампы не найдены")
                return
            
            # Сохранить аннотацию обратно в R2
            updated_json = json_module.dumps(doc.to_dict(), ensure_ascii=False, indent=2)
            if not r2.upload_text(updated_json, ann_r2_key):
                QMessageBox.critical(self, "Ошибка", "Не удалось сохранить аннотацию")
                return
            
            self.status_label.setText(f"🔖 Назначено штампов: {modified_count}")
            QMessageBox.information(
                self, "Успех", 
                f"Штамп назначен на {modified_count} страницах"
            )
            
            # Сигнал для обновления открытого документа
            self.annotation_replaced.emit(r2_key)
            
        except Exception as e:
            logger.error(f"Detect stamps failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка определения штампов:\n{e}")
    
    def _upload_annotation_dialog(self, node: TreeNode):
        """Диалог загрузки аннотации блоков из файла"""
        # Проверка блокировки документа
        if self._check_document_locked(node):
            return
        
        from rd_core.r2_storage import R2Storage
        from app.gui.file_operations import get_annotation_r2_key
        
        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            QMessageBox.warning(self, "Ошибка", "Документ не имеет привязки к R2")
            return
        
        # Диалог выбора файла
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Выберите файл аннотации", 
            "", 
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Читаем содержимое файла
            with open(file_path, 'r', encoding='utf-8') as f:
                json_content = f.read()
            
            # Валидация JSON
            json.loads(json_content)  # Проверяем что это валидный JSON
            
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)
            
            # Загружаем в R2
            if not r2.upload_text(json_content, ann_r2_key):
                QMessageBox.critical(self, "Ошибка", "Не удалось загрузить аннотацию в R2")
                return
            
            logger.info(f"Annotation uploaded to R2: {ann_r2_key}")
            
            # Обновляем флаг has_annotation в узле
            attrs = node.attributes.copy()
            attrs["has_annotation"] = True
            self.client.update_node(node.id, attributes=attrs)
            
            # Регистрируем файл в node_files
            file_size = Path(file_path).stat().st_size
            self.client.upsert_node_file(
                node_id=node.id,
                file_type=FileType.ANNOTATION,
                r2_key=ann_r2_key,
                file_name=Path(ann_r2_key).name,
                file_size=file_size,
                mime_type="application/json",
            )
            
            logger.info(f"Annotation registered in Supabase: node_id={node.id}")
            
            # Обновляем статус PDF и дерево
            from rd_core.pdf_status import calculate_pdf_status, PDFStatus
            
            status, message = calculate_pdf_status(r2, node.id, r2_key)
            self.client.update_pdf_status(node.id, status.value, message)
            
            self.status_label.setText("📤 Аннотация загружена")
            QTimer.singleShot(100, self._refresh_tree)
            
            # Сигнал для обновления открытого документа
            self.annotation_replaced.emit(r2_key)
            
            QMessageBox.information(self, "Успех", "Аннотация блоков успешно загружена")
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in annotation file: {e}")
            QMessageBox.critical(self, "Ошибка", f"Неверный формат JSON:\n{e}")
        except Exception as e:
            logger.error(f"Upload annotation failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки аннотации:\n{e}")
    
    def _view_on_r2(self, node: TreeNode):
        """Показать файлы узла на R2 Storage"""
        import os
        from pathlib import PurePosixPath
        from rd_core.r2_storage import R2Storage
        from app.gui.r2_files_dialog import R2FilesDialog
        
        # Определяем r2_prefix для узла
        if node.node_type == NodeType.DOCUMENT:
            r2_key = node.attributes.get("r2_key", "")
            if r2_key:
                r2_prefix = str(PurePosixPath(r2_key).parent) + "/"
            else:
                r2_prefix = f"tree_docs/{node.id}/"
        else:
            r2_prefix = f"tree_docs/{node.id}/"
        
        self.status_label.setText("Загрузка файлов с R2...")
        
        try:
            r2 = R2Storage()
            r2_objects = r2.list_objects_with_metadata(r2_prefix)
            
            if not r2_objects:
                QMessageBox.information(self, "R2 Storage", f"Нет файлов в папке:\n{r2_prefix}")
                self.status_label.setText("")
                return
            
            # Преобразуем в формат для диалога
            r2_files = self._build_r2_file_tree(r2_objects, r2_prefix)
            
            # Получаем публичный URL R2
            r2_base_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
            r2_base_url = f"{r2_base_url}/{r2_prefix.rstrip('/')}"
            
            # Определяем локальную папку
            from app.gui.folder_settings_dialog import get_projects_dir
            from pathlib import Path
            local_folder = None
            if node.node_type == NodeType.DOCUMENT:
                r2_key = node.attributes.get("r2_key", "")
                if r2_key:
                    projects_dir = get_projects_dir()
                    rel_path = r2_key[len("tree_docs/"):] if r2_key.startswith("tree_docs/") else r2_key
                    local_folder = Path(projects_dir) / Path(rel_path).parent
            
            self.status_label.setText("")
            
            dialog = R2FilesDialog(
                r2_base_url, r2_files, self,
                r2_prefix=r2_prefix,
                node_id=node.id,
                local_folder=local_folder,
            )
            dialog.exec()
            
        except Exception as e:
            logger.error(f"Failed to list R2 files: {e}")
            self.status_label.setText("")
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить список файлов:\n{e}")
    
    def _build_r2_file_tree(self, r2_objects: list, prefix: str) -> list:
        """Построить дерево файлов из списка R2 объектов"""
        from collections import defaultdict
        
        # Группируем по папкам
        folders = defaultdict(list)
        files = []
        
        for obj in r2_objects:
            key = obj.get("Key", "")
            if not key.startswith(prefix):
                continue
            
            rel_path = key[len(prefix):]
            if not rel_path:
                continue
            
            parts = rel_path.split("/")
            if len(parts) == 1:
                # Файл в корне
                ext = rel_path.split(".")[-1].lower() if "." in rel_path else ""
                icon = self._get_file_icon(ext)
                files.append({
                    "name": rel_path,
                    "path": key,
                    "icon": icon,
                    "is_dir": False,
                    "size": obj.get("Size", 0),
                })
            else:
                # Файл в подпапке
                folder_name = parts[0]
                folders[folder_name].append(obj)
        
        result = []
        
        # Добавляем папки
        for folder_name, folder_objects in sorted(folders.items()):
            children = self._build_r2_file_tree(folder_objects, f"{prefix}{folder_name}/")
            result.append({
                "name": folder_name,
                "icon": "📁",
                "is_dir": True,
                "children": children,
            })
        
        # Добавляем файлы
        result.extend(sorted(files, key=lambda x: x["name"]))
        
        return result
    
    def _get_file_icon(self, ext: str) -> str:
        """Получить иконку для расширения файла"""
        icons = {
            "pdf": "📕",
            "json": "📋",
            "md": "📝",
            "png": "🖼️",
            "jpg": "🖼️",
            "jpeg": "🖼️",
            "webp": "🖼️",
            "zip": "📦",
        }
        return icons.get(ext, "📄")
    
    def _save_expanded_state(self):
        """Сохранить состояние раскрытых узлов"""
        try:
            settings = QSettings("RDApp", "ProjectTree")
            settings.setValue("expanded_nodes", list(self._expanded_nodes))
        except Exception as e:
            logger.debug(f"Failed to save expanded state: {e}")
    
    def _load_expanded_state(self):
        """Загрузить состояние раскрытых узлов"""
        try:
            settings = QSettings("RDApp", "ProjectTree")
            expanded_list = settings.value("expanded_nodes", [])
            if expanded_list:
                self._expanded_nodes = set(expanded_list)
            else:
                self._expanded_nodes = set()
        except Exception as e:
            logger.debug(f"Failed to load expanded state: {e}")
            self._expanded_nodes = set()
    
    def _restore_expanded_state(self):
        """Восстановить раскрытое состояние дерева"""
        if not self._expanded_nodes:
            return
        
        def expand_recursive(item: QTreeWidgetItem):
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode) and node.id in self._expanded_nodes:
                # Раскрываем узел
                item.setExpanded(True)
                # Обрабатываем дочерние элементы
                for i in range(item.childCount()):
                    expand_recursive(item.child(i))
        
        # Проходим по всем корневым элементам
        for i in range(self.tree.topLevelItemCount()):
            expand_recursive(self.tree.topLevelItem(i))
    
    def _lock_document(self, node: TreeNode):
        """Заблокировать документ от изменений"""
        try:
            if self.client.lock_document(node.id):
                node.is_locked = True
                self.status_label.setText("🔒 Документ заблокирован")
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self._refresh_tree)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось заблокировать документ")
        except Exception as e:
            logger.error(f"Lock document failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка блокировки: {e}")
    
    def _unlock_document(self, node: TreeNode):
        """Разблокировать документ"""
        try:
            if self.client.unlock_document(node.id):
                node.is_locked = False
                self.status_label.setText("🔓 Документ разблокирован")
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self._refresh_tree)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось разблокировать документ")
        except Exception as e:
            logger.error(f"Unlock document failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка разблокировки: {e}")
    
    def _check_document_locked(self, node: TreeNode) -> bool:
        """
        Проверить заблокирован ли документ.
        Если заблокирован - показать предупреждение и вернуть True.
        Если не заблокирован - вернуть False.
        """
        if node.node_type == NodeType.DOCUMENT and node.is_locked:
            QMessageBox.warning(
                self, 
                "Документ заблокирован", 
                "Этот документ заблокирован от изменений.\nСначала снимите блокировку."
            )
            return True
        return False