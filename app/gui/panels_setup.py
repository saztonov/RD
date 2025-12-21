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
        
        # Блоки (справа)
        self.blocks_dock = QDockWidget("Блоки", self)
        self.blocks_dock.setObjectName("BlocksDock")
        blocks_widget = self._create_blocks_widget()
        self.blocks_dock.setWidget(blocks_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.blocks_dock)
        
        # Устанавливаем размер правого дока
        self.resizeDocks([self.blocks_dock], [320], Qt.Horizontal)
    
    def _create_blocks_widget(self) -> QWidget:
        """Создать виджет блоков"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Кнопка Remote OCR — крупная и заметная
        self.remote_ocr_btn = QPushButton("🚀 Запустить Remote OCR")
        self.remote_ocr_btn.setMinimumHeight(48)
        self.remote_ocr_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-size: 15px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
        """)
        self.remote_ocr_btn.clicked.connect(self._send_to_remote_ocr)
        layout.addWidget(self.remote_ocr_btn)
        
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
    
    def _on_hint_changed(self):
        """Автосохранение подсказки при изменении"""
        if self._selected_image_block:
            self._selected_image_block.hint = self.hint_edit.toPlainText() or None

