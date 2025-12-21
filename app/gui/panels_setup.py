"""
Миксин для создания панелей UI
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
    QTreeWidget,
    QTabWidget,
    QAbstractItemView,
    QPlainTextEdit,
    QDockWidget,
)
from PySide6.QtCore import Qt
from app.gui.page_viewer import PageViewer
from app.gui.project_tree_widget import ProjectTreeWidget


class PanelsSetupMixin:
    """Миксин для создания панелей интерфейса"""
    
    def _setup_ui(self):
        """Настройка интерфейса с док-панелями"""
        # Центральный виджет — только PageViewer
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.page_viewer = PageViewer()
        self.page_viewer.blockDrawn.connect(self._on_block_drawn)
        self.page_viewer.polygonDrawn.connect(self._on_polygon_drawn)
        self.page_viewer.block_selected.connect(self._on_block_selected)
        self.page_viewer.blocks_selected.connect(self._on_blocks_selected)
        self.page_viewer.blockEditing.connect(self._on_block_editing)
        self.page_viewer.blockDeleted.connect(self._on_block_deleted)
        self.page_viewer.blocks_deleted.connect(self._on_blocks_deleted)
        self.page_viewer.blockMoved.connect(self._on_block_moved)
        self.page_viewer.page_changed.connect(self._on_page_changed)
        main_layout.addWidget(self.page_viewer)
        
        # Создаём док-панели
        self._setup_dock_panels()
    
    def _setup_dock_panels(self):
        """Создать все док-панели"""
        # Дерево проектов (слева)
        self.project_dock = QDockWidget("Дерево проектов", self)
        self.project_dock.setObjectName("ProjectTreeDock")
        self.project_tree_widget = ProjectTreeWidget()
        self.project_tree_widget.file_uploaded_r2.connect(self._on_tree_file_uploaded_r2)
        self.project_tree_widget.document_selected.connect(self._on_tree_document_selected)
        self.project_dock.setWidget(self.project_tree_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.project_dock)
        self.resizeDocks([self.project_dock], [280], Qt.Horizontal)
        
        # Блоки (справа сверху)
        self.blocks_dock = QDockWidget("Блоки", self)
        self.blocks_dock.setObjectName("BlocksDock")
        blocks_widget = self._create_blocks_widget()
        self.blocks_dock.setWidget(blocks_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.blocks_dock)
        
        # Инструменты/Настройки (справа снизу)
        self.tools_dock = QDockWidget("Инструменты", self)
        self.tools_dock.setObjectName("ToolsDock")
        tools_widget = self._create_tools_settings_widget()
        self.tools_dock.setWidget(tools_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tools_dock)
        
        # Устанавливаем размеры правых доков
        self.resizeDocks([self.blocks_dock, self.tools_dock], [320, 320], Qt.Horizontal)
    
    def _create_blocks_widget(self) -> QWidget:
        """Создать виджет блоков"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Кнопки перемещения блоков
        move_buttons_layout = QHBoxLayout()
        self.move_block_up_btn = QPushButton("↑ Вверх")
        self.move_block_up_btn.clicked.connect(self._move_block_up)
        move_buttons_layout.addWidget(self.move_block_up_btn)
        
        self.move_block_down_btn = QPushButton("↓ Вниз")
        self.move_block_down_btn.clicked.connect(self._move_block_down)
        move_buttons_layout.addWidget(self.move_block_down_btn)
        
        layout.addLayout(move_buttons_layout)
        
        self.blocks_tabs = QTabWidget()
        
        # Вкладка: Страница → Блок
        self.blocks_tree = QTreeWidget()
        self.blocks_tree.setHeaderLabels(["Название", "Тип"])
        self.blocks_tree.setColumnWidth(0, 150)
        self.blocks_tree.setSortingEnabled(False)
        self.blocks_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.blocks_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.blocks_tree.customContextMenuRequested.connect(
            lambda pos: self.blocks_tree_manager.on_tree_context_menu(pos))
        self.blocks_tree.itemClicked.connect(self._on_tree_block_clicked)
        self.blocks_tree.itemDoubleClicked.connect(self._on_tree_block_double_clicked)
        self.blocks_tree.installEventFilter(self)
        self.blocks_tabs.addTab(self.blocks_tree, "Страница")
        
        layout.addWidget(self.blocks_tabs)
        
        # Подсказка для IMAGE блока
        self.hint_group = QGroupBox("Подсказка (IMAGE)")
        hint_layout = QVBoxLayout(self.hint_group)
        
        self.hint_edit = QPlainTextEdit()
        self.hint_edit.setPlaceholderText("Введите описание содержимого картинки...")
        self.hint_edit.setMaximumHeight(100)
        self.hint_edit.textChanged.connect(self._on_hint_changed)
        hint_layout.addWidget(self.hint_edit)
        
        self.hint_group.setEnabled(False)
        self._selected_image_block = None
        layout.addWidget(self.hint_group)
        
        return widget
    
    def _create_tools_settings_widget(self) -> QWidget:
        """Создать виджет с вкладками Инструменты/Настройки"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.right_tabs = QTabWidget()
        self.right_tabs.setDocumentMode(True)
        
        # Вкладка: Инструменты
        tools_tab = QWidget()
        tools_layout = QVBoxLayout(tools_tab)
        tools_layout.setContentsMargins(4, 4, 4, 4)
        
        self.clear_page_btn = QPushButton("Очистить разметку")
        self.clear_page_btn.clicked.connect(self._clear_current_page)
        tools_layout.addWidget(self.clear_page_btn)
        
        self.save_draft_btn = QPushButton("💾 Сохранить черновик на сервере")
        self.save_draft_btn.clicked.connect(self._save_draft_to_server)
        tools_layout.addWidget(self.save_draft_btn)
        
        self.remote_ocr_btn = QPushButton("Запустить Remote OCR")
        self.remote_ocr_btn.clicked.connect(self._send_to_remote_ocr)
        tools_layout.addWidget(self.remote_ocr_btn)
        
        tools_layout.addStretch()
        self.right_tabs.addTab(tools_tab, "🛠️ Инструменты")
        
        layout.addWidget(self.right_tabs)
        return widget
    
    def _on_hint_changed(self):
        """Автосохранение подсказки при изменении"""
        if self._selected_image_block:
            self._selected_image_block.hint = self.hint_edit.toPlainText() or None
    
    def _create_blocks_group(self) -> QGroupBox:
        """Создать группу списка блоков"""
        blocks_group = QGroupBox("Все блоки")
        blocks_layout = QVBoxLayout(blocks_group)
        
        # Кнопки перемещения блоков
        move_buttons_layout = QHBoxLayout()
        self.move_block_up_btn = QPushButton("↑ Вверх")
        self.move_block_up_btn.clicked.connect(self._move_block_up)
        move_buttons_layout.addWidget(self.move_block_up_btn)
        
        self.move_block_down_btn = QPushButton("↓ Вниз")
        self.move_block_down_btn.clicked.connect(self._move_block_down)
        move_buttons_layout.addWidget(self.move_block_down_btn)
        
        blocks_layout.addLayout(move_buttons_layout)
        
        self.blocks_tabs = QTabWidget()
        
        # Вкладка: Страница → Блок
        self.blocks_tree = QTreeWidget()
        self.blocks_tree.setHeaderLabels(["Название", "Тип"])
        self.blocks_tree.setColumnWidth(0, 150)
        self.blocks_tree.setSortingEnabled(False)  # Отключаем встроенную сортировку
        self.blocks_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.blocks_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.blocks_tree.customContextMenuRequested.connect(
            lambda pos: self.blocks_tree_manager.on_tree_context_menu(pos))
        self.blocks_tree.itemClicked.connect(self._on_tree_block_clicked)
        self.blocks_tree.itemDoubleClicked.connect(self._on_tree_block_double_clicked)
        self.blocks_tree.installEventFilter(self)
        self.blocks_tabs.addTab(self.blocks_tree, "Страница")
        
        blocks_layout.addWidget(self.blocks_tabs)
        return blocks_group
    
    def _create_hint_group(self) -> QGroupBox:
        """Создать группу подсказки для IMAGE блока"""
        self.hint_group = QGroupBox("Подсказка (IMAGE)")
        hint_layout = QVBoxLayout(self.hint_group)
        
        self.hint_edit = QPlainTextEdit()
        self.hint_edit.setPlaceholderText("Введите описание содержимого картинки...")
        self.hint_edit.setMaximumHeight(100)
        self.hint_edit.textChanged.connect(self._on_hint_changed)
        hint_layout.addWidget(self.hint_edit)
        
        # Неактивен по умолчанию
        self.hint_group.setEnabled(False)
        self._selected_image_block = None
        
        return self.hint_group
    
    def _on_hint_changed(self):
        """Автосохранение подсказки при изменении"""
        if self._selected_image_block:
            self._selected_image_block.hint = self.hint_edit.toPlainText() or None
    
    def _create_actions_group(self) -> QGroupBox:
        """Создать группу действий"""
        actions_group = QGroupBox("Действия")
        actions_layout = QVBoxLayout(actions_group)
        
        self.clear_page_btn = QPushButton("Очистить разметку")
        self.clear_page_btn.clicked.connect(self._clear_current_page)
        actions_layout.addWidget(self.clear_page_btn)
        
        self.save_draft_btn = QPushButton("💾 Сохранить черновик на сервере")
        self.save_draft_btn.clicked.connect(self._save_draft_to_server)
        actions_layout.addWidget(self.save_draft_btn)
        
        self.remote_ocr_btn = QPushButton("Запустить Remote OCR")
        self.remote_ocr_btn.clicked.connect(self._send_to_remote_ocr)
        actions_layout.addWidget(self.remote_ocr_btn)
        
        return actions_group
