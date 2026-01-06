"""Виджет дерева проектов с поддержкой Supabase"""
from __future__ import annotations

import logging
from typing import Dict, List

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.sync_check_worker import SyncCheckWorker, SyncStatus
from app.gui.tree_context_menu import TreeContextMenuMixin
from app.gui.tree_delegates import VersionHighlightDelegate
from app.gui.tree_filter_mixin import TreeFilterMixin
from app.gui.tree_node_operations import STATUS_COLORS, TreeNodeOperationsMixin
from app.gui.tree_sync_mixin import TreeSyncMixin
from app.tree_client import NodeType, TreeClient, TreeNode

from .annotation_operations import AnnotationOperations
from .pdf_status_manager import PDFStatusManager
from .r2_viewer_integration import R2ViewerIntegration
from .tree_item_builder import TreeItemBuilder

logger = logging.getLogger(__name__)

__all__ = ["ProjectTreeWidget"]


class ProjectTreeWidget(
    TreeNodeOperationsMixin,
    TreeSyncMixin,
    TreeFilterMixin,
    TreeContextMenuMixin,
    QWidget,
):
    """Виджет дерева проектов"""

    document_selected = Signal(str, str)  # node_id, r2_key
    file_uploaded_r2 = Signal(str, str)  # node_id, r2_key
    annotation_replaced = Signal(str)  # r2_key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = TreeClient()
        self._node_map: Dict[str, QTreeWidgetItem] = {}
        self._stage_types: List = []
        self._section_types: List = []
        self._loading = False
        self._current_document_id: str = ""
        self._auto_refresh_timer: QTimer = None
        self._last_node_count: int = 0
        self._sync_statuses: Dict[str, SyncStatus] = {}
        self._sync_worker: SyncCheckWorker = None
        self._expanded_nodes: set = set()

        # Вспомогательные компоненты
        self._pdf_status_manager = PDFStatusManager(self)
        self._annotation_ops = AnnotationOperations(self)
        self._r2_viewer = R2ViewerIntegration(self)
        self._item_builder = TreeItemBuilder(self)

        self._setup_ui()
        self._setup_auto_refresh()
        QTimer.singleShot(100, self._initial_load)

    def _setup_auto_refresh(self):
        """Настроить автообновление"""
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_tree)
        self._auto_refresh_timer.start(30000)

        self._cache_cleanup_timer = QTimer(self)
        self._cache_cleanup_timer.timeout.connect(self._pdf_status_manager.cleanup_cache)
        self._cache_cleanup_timer.start(60000)

        self._pdf_status_refresh_timer = QTimer(self)
        self._pdf_status_refresh_timer.timeout.connect(self._pdf_status_manager.auto_refresh)
        self._pdf_status_refresh_timer.start(30000)

    def _auto_refresh_tree(self):
        """Автоматическое обновление дерева"""
        if self._loading:
            return

        try:
            roots = self.client.get_root_nodes()
            current_count = len(roots)

            if current_count != self._last_node_count:
                self._last_node_count = current_count
                self._refresh_tree()
                return

            for root in roots:
                if root.id in self._node_map:
                    item = self._node_map[root.id]
                    old_node = item.data(0, Qt.UserRole)
                    if isinstance(old_node, TreeNode):
                        if old_node.updated_at != root.updated_at:
                            self._refresh_tree()
                            return
                else:
                    self._refresh_tree()
                    return
        except Exception as e:
            logger.debug(f"Auto-refresh check failed: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._create_header()
        layout.addWidget(header)

        # Search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c; color: #e0e0e0;
                border: 1px solid #555; padding: 6px; border-radius: 2px;
            }
            QLineEdit:focus { border: 1px solid #0e639c; }
        """)
        self.search_input.textChanged.connect(self._filter_tree)
        layout.addWidget(self.search_input)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFrameShape(QFrame.NoFrame)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemCollapsed.connect(self._on_item_collapsed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.installEventFilter(self)
        self.tree.setStyleSheet("""
            QTreeWidget { background-color: #1e1e1e; color: #e0e0e0; outline: none; border: none; }
            QTreeWidget::item { padding: 4px; border-radius: 2px; }
            QTreeWidget::item:hover { background-color: #2a2d2e; }
            QTreeWidget::item:selected { background-color: #094771; }
        """)
        self.tree.setItemDelegate(VersionHighlightDelegate(self.tree))
        layout.addWidget(self.tree)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 8pt; padding: 4px;")
        layout.addWidget(self.status_label)

        # Статистика документов
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet(
            "color: #888; font-size: 8pt; padding: 4px; background-color: #252526; "
            "border-top: 1px solid #3e3e42;"
        )
        layout.addWidget(self.stats_label)

    def _create_header(self) -> QWidget:
        """Создать заголовок с кнопками"""
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

        # Create button
        self.create_btn = QPushButton("+ Проект")
        self.create_btn.setCursor(Qt.PointingHandCursor)
        self.create_btn.setStyleSheet("""
            QPushButton { background-color: #0e639c; color: white; border: none;
                         padding: 6px 16px; border-radius: 4px; font-weight: 500; }
            QPushButton:hover { background-color: #1177bb; }
            QPushButton:pressed { background-color: #0a4d78; }
        """)
        self.create_btn.clicked.connect(self._create_project)

        icon_btn_style = """
            QPushButton { background-color: #3e3e42; color: #cccccc; border: none;
                         border-radius: 4px; font-size: 12px; font-weight: bold; }
            QPushButton:hover { background-color: #505054; color: #ffffff; }
            QPushButton:pressed { background-color: #0e639c; }
        """

        self.refresh_btn = self._create_icon_btn("↻", "Обновить", self._refresh_tree, icon_btn_style)
        self.expand_all_btn = self._create_icon_btn("▼", "Развернуть все", self._expand_all, icon_btn_style)
        self.collapse_all_btn = self._create_icon_btn("▲", "Свернуть все", self._collapse_all, icon_btn_style)
        self.sync_check_btn = self._create_icon_btn("🔄", "Проверить синхронизацию", self._start_sync_check, icon_btn_style)

        btns_layout.addWidget(self.create_btn)
        btns_layout.addWidget(self.refresh_btn)
        btns_layout.addWidget(self.expand_all_btn)
        btns_layout.addWidget(self.collapse_all_btn)
        btns_layout.addWidget(self.sync_check_btn)
        header_layout.addLayout(btns_layout)

        return header

    def _create_icon_btn(self, text: str, tooltip: str, callback, style: str) -> QPushButton:
        """Создать иконочную кнопку"""
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setFixedSize(32, 32)
        btn.setStyleSheet(style)
        btn.clicked.connect(callback)
        return btn

    def _initial_load(self):
        """Начальная загрузка"""
        if not self.client.is_available():
            self.status_label.setText("⚠ Supabase недоступен")
            return
        self._load_expanded_state()
        self.refresh_types()
        self._refresh_tree()

    def refresh_types(self):
        """Обновить кэшированные типы"""
        try:
            self._stage_types = self.client.get_stage_types()
            self._section_types = self.client.get_section_types()
        except Exception as e:
            logger.error(f"Failed to load types: {e}")

    def _expand_all(self):
        self.tree.expandAll()

    def _collapse_all(self):
        self.tree.collapseAll()

    def _refresh_tree(self):
        """Обновить дерево"""
        if self._loading:
            return

        self._loading = True
        self._pdf_status_manager.reset()
        self.status_label.setText("Загрузка...")
        self.tree.clear()
        self._node_map.clear()
        self._sync_statuses.clear()

        try:
            roots = self.client.get_root_nodes()
            self._last_node_count = len(roots)
            for node in roots:
                item = self._item_builder.create_item(node)
                self.tree.addTopLevelItem(item)
                self._item_builder.add_placeholder(item, node)

            self.status_label.setText(f"Проектов: {len(roots)}")

            QTimer.singleShot(100, self._restore_expanded_state)
            QTimer.singleShot(300, self._update_stats)
            QTimer.singleShot(500, self._start_sync_check)

            if not self._pdf_status_manager.is_loaded:
                QTimer.singleShot(200, self._pdf_status_manager.load_batch)
        except Exception as e:
            logger.error(f"Failed to refresh tree: {e}")
            self.status_label.setText(f"Ошибка: {e}")
        finally:
            self._loading = False

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Lazy loading при раскрытии"""
        node = item.data(0, Qt.UserRole)
        if isinstance(node, TreeNode):
            self._expanded_nodes.add(node.id)
            self._save_expanded_state()

        if item.childCount() == 1:
            child = item.child(0)
            if child.data(0, Qt.UserRole) == "placeholder":
                if isinstance(node, TreeNode):
                    item.removeChild(child)
                    self._load_children(item, node)
                    QTimer.singleShot(100, self._start_sync_check)

    def _on_item_collapsed(self, item: QTreeWidgetItem):
        node = item.data(0, Qt.UserRole)
        if isinstance(node, TreeNode):
            self._expanded_nodes.discard(node.id)
            self._save_expanded_state()

    def _load_children(self, parent_item: QTreeWidgetItem, parent_node: TreeNode):
        """Загрузить дочерние узлы"""
        try:
            children = self.client.get_children(parent_node.id)
            for child in children:
                child_item = self._item_builder.create_item(child)
                parent_item.addChild(child_item)
                self._item_builder.add_placeholder(child_item, child)
        except Exception as e:
            logger.error(f"Failed to load children: {e}")

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Двойной клик - открыть документ"""
        data = item.data(0, Qt.UserRole)
        if isinstance(data, TreeNode) and data.node_type == NodeType.DOCUMENT:
            r2_key = data.attributes.get("r2_key", "")
            if r2_key:
                self.highlight_document(data.id)
                self.document_selected.emit(data.id, r2_key)

    def highlight_document(self, node_id: str):
        """Подсветить текущий открытый документ"""
        if self._current_document_id and self._current_document_id in self._node_map:
            prev_item = self._node_map[self._current_document_id]
            prev_node = prev_item.data(0, Qt.UserRole)
            if isinstance(prev_node, TreeNode):
                prev_item.setBackground(0, QColor("transparent"))
                prev_item.setForeground(0, QColor(STATUS_COLORS.get(prev_node.status, "#e0e0e0")))

        self._current_document_id = node_id
        if node_id and node_id in self._node_map:
            item = self._node_map[node_id]
            item.setBackground(0, QColor("#264f78"))
            item.setForeground(0, QColor("#ffffff"))
            self.tree.scrollToItem(item)

    def eventFilter(self, obj, event):
        if obj == self.tree and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Delete:
                item = self.tree.currentItem()
                if item:
                    node = item.data(0, Qt.UserRole)
                    if isinstance(node, TreeNode):
                        self._delete_node(node)
                        return True
        return super().eventFilter(obj, event)

    # Делегация к компонентам
    def _copy_annotation(self, node: TreeNode):
        self._annotation_ops.copy_annotation(node)

    def _paste_annotation(self, node: TreeNode):
        self._annotation_ops.paste_annotation(node)

    def _detect_and_assign_stamps(self, node: TreeNode):
        self._annotation_ops.detect_and_assign_stamps(node)

    def _upload_annotation_dialog(self, node: TreeNode):
        self._annotation_ops.upload_from_file(node)

    def _view_on_r2(self, node: TreeNode):
        self._r2_viewer.view_on_r2(node)

    def _get_pdf_status_icon(self, status: str) -> str:
        return PDFStatusManager.get_status_icon(status)

    # Управление блокировкой документов
    def _lock_document(self, node: TreeNode):
        try:
            if self.client.lock_document(node.id):
                node.is_locked = True
                self.status_label.setText("🔒 Документ заблокирован")
                self._update_main_window_lock_state(node.id, True)
                QTimer.singleShot(100, self._refresh_tree)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось заблокировать документ")
        except Exception as e:
            logger.error(f"Lock document failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка блокировки: {e}")

    def _unlock_document(self, node: TreeNode):
        try:
            if self.client.unlock_document(node.id):
                node.is_locked = False
                self.status_label.setText("🔓 Документ разблокирован")
                self._update_main_window_lock_state(node.id, False)
                QTimer.singleShot(100, self._refresh_tree)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось разблокировать документ")
        except Exception as e:
            logger.error(f"Unlock document failed: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка разблокировки: {e}")

    def _update_main_window_lock_state(self, node_id: str, locked: bool):
        """Обновить состояние блокировки в главном окне"""
        main_window = self.window()
        if hasattr(main_window, "_current_node_id") and main_window._current_node_id == node_id:
            main_window._current_node_locked = locked
            if hasattr(main_window, "page_viewer"):
                main_window.page_viewer.read_only = locked
            if hasattr(main_window, "move_block_up_btn"):
                main_window.move_block_up_btn.setEnabled(not locked)
            if hasattr(main_window, "move_block_down_btn"):
                main_window.move_block_down_btn.setEnabled(not locked)

    def _check_document_locked(self, node: TreeNode) -> bool:
        if node.node_type == NodeType.DOCUMENT and node.is_locked:
            QMessageBox.warning(self, "Документ заблокирован",
                              "Этот документ заблокирован от изменений.\nСначала снимите блокировку.")
            return True
        return False

    def _verify_blocks(self, node: TreeNode):
        from app.gui.block_verification_dialog import BlockVerificationDialog
        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            QMessageBox.warning(self, "Ошибка", "Документ не имеет привязки к R2")
            return
        dialog = BlockVerificationDialog(node.name, r2_key, self)
        dialog.exec()

    def _view_in_supabase(self, node: TreeNode):
        from app.gui.node_files_dialog import NodeFilesDialog
        dialog = NodeFilesDialog(node, self.client, self)
        dialog.exec()

    # Сохранение состояния
    def _save_expanded_state(self):
        try:
            settings = QSettings("RDApp", "ProjectTree")
            settings.setValue("expanded_nodes", list(self._expanded_nodes))
        except Exception as e:
            logger.debug(f"Failed to save expanded state: {e}")

    def _load_expanded_state(self):
        try:
            settings = QSettings("RDApp", "ProjectTree")
            expanded_list = settings.value("expanded_nodes", [])
            self._expanded_nodes = set(expanded_list) if expanded_list else set()
        except Exception as e:
            logger.debug(f"Failed to load expanded state: {e}")
            self._expanded_nodes = set()

    def _restore_expanded_state(self):
        if not self._expanded_nodes:
            return

        def expand_recursive(item: QTreeWidgetItem):
            node = item.data(0, Qt.UserRole)
            if isinstance(node, TreeNode) and node.id in self._expanded_nodes:
                item.setExpanded(True)
                for i in range(item.childCount()):
                    expand_recursive(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            expand_recursive(self.tree.topLevelItem(i))

    # Свойство для доступа к скопированной аннотации (для контекстного меню)
    @property
    def _copied_annotation(self) -> Dict:
        return self._annotation_ops._copied_annotation

    def _update_stats(self):
        """Обновить статистику документов"""
        try:
            # Получаем все узлы из БД для подсчёта
            stats = self.client.get_tree_stats()

            pdf_count = stats.get("pdf_count", 0)
            md_count = stats.get("md_count", 0)
            folders_with_pdf = stats.get("folders_with_pdf", 0)

            self.stats_label.setText(
                f"📄 PDF: {pdf_count}  |  📝 MD: {md_count}  |  📁 Папок с PDF: {folders_with_pdf}"
            )
        except Exception as e:
            logger.debug(f"Failed to update stats: {e}")
            self.stats_label.setText("")
