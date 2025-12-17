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
    QSplitter,
)
from PySide6.QtCore import Qt
from app.gui.page_viewer import PageViewer
from app.gui.project_sidebar import ProjectSidebar


class PanelsSetupMixin:
    """Миксин для создания панелей интерфейса"""
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Главный сплиттер для изменения размеров панелей
        self.main_splitter = QSplitter(Qt.Horizontal)
        
        # Боковая панель проектов + задания
        left_sidebar = self._create_left_sidebar()
        self.main_splitter.addWidget(left_sidebar)
        
        # Левая панель: просмотр страниц
        left_panel = self._create_left_panel()
        self.main_splitter.addWidget(left_panel)
        
        # Правая панель: инструменты и свойства блоков
        right_panel = self._create_right_panel()
        self.main_splitter.addWidget(right_panel)
        
        # Устанавливаем начальные размеры (левая боковая 280, центр 600, правая 320)
        self.main_splitter.setSizes([280, 600, 320])
        self.main_splitter.setStretchFactor(0, 0)  # Боковая панель не растягивается
        self.main_splitter.setStretchFactor(1, 1)  # Центр растягивается
        self.main_splitter.setStretchFactor(2, 0)  # Правая панель не растягивается
        
        main_layout.addWidget(self.main_splitter)
    
    def _create_left_sidebar(self) -> QWidget:
        """Создать боковую панель проектов"""
        left_sidebar = QWidget()
        left_sidebar_layout = QVBoxLayout(left_sidebar)
        left_sidebar_layout.setContentsMargins(5, 5, 5, 5)
        left_sidebar_layout.setSpacing(5)
        
        self.project_sidebar = ProjectSidebar(self.project_manager)
        self.project_sidebar.project_switched.connect(self._on_project_switched)
        self.project_sidebar.file_switched.connect(self._on_file_switched)
        self.project_manager.file_removed.connect(self._on_file_removed)
        self.project_manager.project_removed.connect(self._on_project_removed)
        left_sidebar_layout.addWidget(self.project_sidebar, stretch=1)
        
        left_sidebar.setMinimumWidth(200)
        return left_sidebar
    
    def _create_left_panel(self) -> QWidget:
        """Создать левую панель с просмотром страниц"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
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
        layout.addWidget(self.page_viewer)
        
        return panel
    
    def _create_right_panel(self) -> QWidget:
        """Создать правую панель с инструментами"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Группа: список блоков
        blocks_group = self._create_blocks_group()
        layout.addWidget(blocks_group)
        
        # Группа: действия
        actions_group = self._create_actions_group()
        layout.addWidget(actions_group)
        
        return panel
    
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
