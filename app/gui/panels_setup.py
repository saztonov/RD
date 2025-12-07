"""
Миксин для создания панелей UI
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QComboBox, QGroupBox, QLineEdit,
                               QTreeWidget, QTabWidget, QListWidget, QAbstractItemView)
from PySide6.QtCore import Qt
from app.models import BlockType
from app.gui.page_viewer import PageViewer
from app.gui.project_sidebar import ProjectSidebar
from app.gui.task_sidebar import TaskSidebar


class PanelsSetupMixin:
    """Миксин для создания панелей интерфейса"""
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        # Боковая панель проектов + задания
        left_sidebar = self._create_left_sidebar()
        main_layout.addWidget(left_sidebar)
        
        # Левая панель: просмотр страниц
        left_panel = self._create_left_panel()
        main_layout.addWidget(left_panel, stretch=3)
        
        # Правая панель: инструменты и свойства блоков
        right_panel = self._create_right_panel()
        main_layout.addWidget(right_panel, stretch=1)
    
    def _create_left_sidebar(self) -> QWidget:
        """Создать боковую панель проектов"""
        left_sidebar = QWidget()
        left_sidebar_layout = QVBoxLayout(left_sidebar)
        left_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        left_sidebar_layout.setSpacing(5)
        
        self.project_sidebar = ProjectSidebar(self.project_manager)
        self.project_sidebar.project_switched.connect(self._on_project_switched)
        self.project_sidebar.file_switched.connect(self._on_file_switched)
        self.project_manager.file_removed.connect(self._on_file_removed)
        left_sidebar_layout.addWidget(self.project_sidebar, stretch=2)
        
        self.task_sidebar = TaskSidebar(self.task_manager)
        left_sidebar_layout.addWidget(self.task_sidebar, stretch=1)
        
        left_sidebar.setMaximumWidth(320)
        left_sidebar.setMinimumWidth(280)
        return left_sidebar
    
    def _create_left_panel(self) -> QWidget:
        """Создать левую панель с просмотром страниц"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        self.page_viewer = PageViewer()
        self.page_viewer.blockDrawn.connect(self._on_block_drawn)
        self.page_viewer.block_selected.connect(self._on_block_selected)
        self.page_viewer.blocks_selected.connect(self._on_blocks_selected)
        self.page_viewer.blockEditing.connect(self._on_block_editing)
        self.page_viewer.blockDeleted.connect(self._on_block_deleted)
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
        
        # Группа: свойства блока
        block_group = self._create_block_properties_group()
        layout.addWidget(block_group)
        
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
        
        # Вкладка 1: Страница → Категория → Блок
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
        
        # Вкладка 2: Категория → Блок → Страница
        self.blocks_tree_by_category = QTreeWidget()
        self.blocks_tree_by_category.setHeaderLabels(["Название", "Тип"])
        self.blocks_tree_by_category.setColumnWidth(0, 150)
        self.blocks_tree_by_category.setSortingEnabled(False)  # Отключаем встроенную сортировку
        self.blocks_tree_by_category.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.blocks_tree_by_category.setContextMenuPolicy(Qt.CustomContextMenu)
        self.blocks_tree_by_category.customContextMenuRequested.connect(
            lambda pos: self.blocks_tree_manager.on_tree_context_menu(pos))
        self.blocks_tree_by_category.itemClicked.connect(self._on_tree_block_clicked)
        self.blocks_tree_by_category.itemDoubleClicked.connect(self._on_tree_block_double_clicked)
        self.blocks_tree_by_category.installEventFilter(self)
        self.blocks_tabs.addTab(self.blocks_tree_by_category, "Категория")
        
        blocks_layout.addWidget(self.blocks_tabs)
        return blocks_group
    
    def _create_block_properties_group(self) -> QGroupBox:
        """Создать группу свойств блока"""
        block_group = QGroupBox("Свойства блока")
        block_layout = QVBoxLayout(block_group)
        
        # Тип блока
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Тип:"))
        self.block_type_combo = QComboBox()
        self.block_type_combo.addItems([t.value for t in BlockType])
        self.block_type_combo.currentTextChanged.connect(self._on_block_type_changed)
        type_layout.addWidget(self.block_type_combo)
        
        # Кнопки редактирования промтов
        self.edit_text_prompt_btn = QPushButton("✏️")
        self.edit_text_prompt_btn.setMaximumWidth(30)
        self.edit_text_prompt_btn.setToolTip("Редактировать промт для Текста")
        self.edit_text_prompt_btn.clicked.connect(lambda: self._edit_type_prompt("text", "Текст"))
        type_layout.addWidget(self.edit_text_prompt_btn)
        
        self.edit_table_prompt_btn = QPushButton("✏️")
        self.edit_table_prompt_btn.setMaximumWidth(30)
        self.edit_table_prompt_btn.setToolTip("Редактировать промт для Таблицы")
        self.edit_table_prompt_btn.clicked.connect(lambda: self._edit_type_prompt("table", "Таблица"))
        type_layout.addWidget(self.edit_table_prompt_btn)
        
        self.edit_image_prompt_btn = QPushButton("✏️")
        self.edit_image_prompt_btn.setMaximumWidth(30)
        self.edit_image_prompt_btn.setToolTip("Редактировать промт для Картинки")
        self.edit_image_prompt_btn.clicked.connect(lambda: self._edit_type_prompt("image", "Картинка"))
        type_layout.addWidget(self.edit_image_prompt_btn)
        
        block_layout.addLayout(type_layout)
        
        # Категория
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("Категория:"))
        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("Введите категорию...")
        self.category_edit.editingFinished.connect(self._on_category_changed)
        cat_layout.addWidget(self.category_edit)
        
        self.add_category_btn = QPushButton("➕")
        self.add_category_btn.setMaximumWidth(30)
        self.add_category_btn.setToolTip("Добавить новую категорию")
        self.add_category_btn.clicked.connect(lambda: self.category_manager.add_category())
        cat_layout.addWidget(self.add_category_btn)
        block_layout.addLayout(cat_layout)
        
        # Список категорий
        categories_header = QHBoxLayout()
        categories_header.addWidget(QLabel("Категории:"))
        self.edit_category_prompt_btn = QPushButton("✏️ Промт")
        self.edit_category_prompt_btn.setMaximumWidth(80)
        self.edit_category_prompt_btn.setToolTip("Редактировать промт выбранной категории")
        self.edit_category_prompt_btn.clicked.connect(self._edit_selected_category_prompt)
        categories_header.addWidget(self.edit_category_prompt_btn)
        block_layout.addLayout(categories_header)
        
        self.categories_list = QListWidget()
        self.categories_list.setMaximumHeight(80)
        self.categories_list.itemClicked.connect(
            lambda item: self.category_manager.on_category_clicked(item))
        self.categories_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.categories_list.customContextMenuRequested.connect(self._show_category_context_menu)
        block_layout.addWidget(self.categories_list)
        
        return block_group
    
    def _create_actions_group(self) -> QGroupBox:
        """Создать группу действий"""
        actions_group = QGroupBox("Действия")
        actions_layout = QVBoxLayout(actions_group)
        
        # Paddle
        self.paddle_segment_btn = QPushButton("Paddle разметка")
        self.paddle_segment_btn.clicked.connect(self._paddle_segment_pdf)
        actions_layout.addWidget(self.paddle_segment_btn)
        
        self.paddle_all_btn = QPushButton("Paddle (все страницы)")
        self.paddle_all_btn.clicked.connect(self._paddle_segment_all_pages)
        actions_layout.addWidget(self.paddle_all_btn)
        
        actions_layout.addWidget(QLabel(""))
        
        # Очистка
        self.clear_page_btn = QPushButton("Очистить разметку")
        self.clear_page_btn.clicked.connect(self._clear_current_page)
        actions_layout.addWidget(self.clear_page_btn)
        
        actions_layout.addWidget(QLabel(""))
        
        self.run_ocr_btn = QPushButton("Запустить OCR")
        self.run_ocr_btn.clicked.connect(self._run_ocr_all)
        actions_layout.addWidget(self.run_ocr_btn)
        
        return actions_group
    
    def _edit_type_prompt(self, prompt_type: str, display_name: str):
        """Редактировать промт типа блока"""
        if hasattr(self, 'prompt_manager'):
            default_prompt = self.prompt_manager.DEFAULT_PROMPTS.get(prompt_type, "")
            self.prompt_manager.edit_prompt(
                prompt_type,
                f"Редактирование промта: {display_name}",
                default_prompt
            )
    
    def _edit_selected_category_prompt(self):
        """Редактировать промт выбранной категории"""
        selected_items = self.categories_list.selectedItems()
        if not selected_items:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Внимание", "Выберите категорию из списка")
            return
        
        category_name = selected_items[0].text()
        if hasattr(self, 'category_manager'):
            self.category_manager.edit_category_prompt(category_name)
    
    def _show_category_context_menu(self, position):
        """Показать контекстное меню для категории"""
        from PySide6.QtWidgets import QMenu
        
        item = self.categories_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu()
        category_name = item.text()
        
        edit_prompt_action = menu.addAction("✏️ Редактировать промт")
        edit_prompt_action.triggered.connect(lambda: self.category_manager.edit_category_prompt(category_name))
        
        delete_action = menu.addAction("🗑️ Удалить категорию")
        delete_action.triggered.connect(lambda: self.category_manager.delete_category(category_name))
        
        menu.exec(self.categories_list.mapToGlobal(position))

