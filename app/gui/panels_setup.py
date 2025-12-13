"""
Миксин для создания панелей UI
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QComboBox, QGroupBox, QLineEdit,
                               QTreeWidget, QTabWidget, QListWidget, QAbstractItemView,
                               QTreeWidgetItem, QSplitter, QHeaderView)
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
        left_sidebar_layout.addWidget(self.project_sidebar, stretch=2)
        
        self.task_sidebar = TaskSidebar(self.task_manager)
        left_sidebar_layout.addWidget(self.task_sidebar, stretch=1)
        
        left_sidebar.setMinimumWidth(200)
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
        
        # Группа: свойства блока
        block_group = self._create_block_properties_group()
        layout.addWidget(block_group)
        
        # Группа: промты
        prompts_group = self._create_prompts_group()
        layout.addWidget(prompts_group)
        
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
        """Создать группу категорий"""
        block_group = QGroupBox("Категории")
        block_layout = QVBoxLayout(block_group)
        
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
        self.categories_list = QListWidget()
        self.categories_list.setMaximumHeight(150)
        self.categories_list.itemClicked.connect(
            lambda item: self.category_manager.on_category_clicked(item))
        self.categories_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.categories_list.customContextMenuRequested.connect(self._show_category_context_menu)
        block_layout.addWidget(self.categories_list)
        
        return block_group
    
    def _create_prompts_group(self) -> QGroupBox:
        """Создать группу промтов"""
        prompts_group = QGroupBox("Промты")
        prompts_layout = QVBoxLayout(prompts_group)
        
        # Список промтов с колонками: #, Название, Тип, Обновлено
        self.prompts_tree = QTreeWidget()
        self.prompts_tree.setHeaderLabels(["#", "Название", "Тип", "Обновлено"])
        self.prompts_tree.setColumnWidth(0, 30)
        self.prompts_tree.setColumnWidth(1, 120)
        self.prompts_tree.setColumnWidth(2, 70)
        self.prompts_tree.setColumnWidth(3, 100)
        self.prompts_tree.setSortingEnabled(True)
        self.prompts_tree.sortByColumn(1, Qt.AscendingOrder)
        self.prompts_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.prompts_tree.setMaximumHeight(200)
        self.prompts_tree.itemSelectionChanged.connect(self._on_prompt_selection_changed)
        self.prompts_tree.itemDoubleClicked.connect(lambda: self._edit_selected_prompt())
        
        # Настройка заголовка для сортировки
        header = self.prompts_tree.header()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        
        prompts_layout.addWidget(self.prompts_tree)
        
        # Кнопка редактирования промта
        self.edit_prompt_btn = QPushButton("✏️ Редактировать промт")
        self.edit_prompt_btn.setEnabled(False)
        self.edit_prompt_btn.clicked.connect(self._edit_selected_prompt)
        prompts_layout.addWidget(self.edit_prompt_btn)
        
        # Заполняем список начальными данными
        self._populate_prompts_tree()
        
        return prompts_group
    
    def _populate_prompts_tree(self):
        """Заполнить список промтов с данными из R2"""
        self.prompts_tree.clear()
        
        # Получаем промты с метаданными из R2
        prompts_data = []
        if hasattr(self, 'prompt_manager') and self.prompt_manager.r2_storage:
            prompts_data = self.prompt_manager.list_prompts_with_metadata()
        
        # Создаем словарь дат по именам
        dates_map = {}
        for p in prompts_data:
            dates_map[p['name']] = p.get('last_modified')
        
        row_num = 1
        
        # Добавляем типы блоков
        block_types = [
            ("Текст", "text", "Блок"),
            ("Таблица", "table", "Блок"),
            ("Картинка", "image", "Блок")
        ]
        
        for display_name, key, type_str in block_types:
            item = QTreeWidgetItem(self.prompts_tree)
            item.setText(0, str(row_num))
            item.setText(1, display_name)
            item.setText(2, type_str)
            
            # Дата обновления
            last_mod = dates_map.get(key)
            if last_mod:
                item.setText(3, last_mod.strftime("%d.%m.%Y %H:%M"))
            else:
                item.setText(3, "—")
            
            item.setData(0, Qt.UserRole, key)  # Сохраняем ключ
            row_num += 1
        
        # Добавляем категории
        if hasattr(self, 'categories'):
            for category in sorted(self.categories):
                item = QTreeWidgetItem(self.prompts_tree)
                item.setText(0, str(row_num))
                item.setText(1, category)
                item.setText(2, "Категория")
                
                # Дата обновления
                cat_key = f"category_{category}"
                last_mod = dates_map.get(cat_key)
                if last_mod:
                    item.setText(3, last_mod.strftime("%d.%m.%Y %H:%M"))
                else:
                    item.setText(3, "—")
                
                item.setData(0, Qt.UserRole, cat_key)
                row_num += 1
    
    def update_prompts_table(self):
        """Обновить список промтов (публичный метод)"""
        if hasattr(self, 'prompts_tree'):
            self._populate_prompts_tree()
    
    def _on_prompt_selection_changed(self):
        """Обработчик изменения выбора в списке промтов"""
        selected = self.prompts_tree.selectedItems()
        self.edit_prompt_btn.setEnabled(len(selected) > 0)
    
    def _edit_selected_prompt(self):
        """Редактировать выбранный промт"""
        current_item = self.prompts_tree.currentItem()
        if not current_item:
            return
        
        display_name = current_item.text(1)
        prompt_type = current_item.text(2)
        prompt_key = current_item.data(0, Qt.UserRole)
        
        if not hasattr(self, 'prompt_manager'):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Ошибка", "PromptManager не инициализирован")
            return
        
        if prompt_type == "Блок":
            # Редактируем промт типа блока (из R2)
            if prompt_key:
                self.prompt_manager.edit_prompt(
                    prompt_key,
                    f"Редактирование промта: {display_name}",
                    None  # Промт загрузится из R2
                )
                self._populate_prompts_tree()  # Обновляем список после редактирования
        elif prompt_type == "Категория":
            # Редактируем промт категории (из R2)
            if hasattr(self, 'category_manager'):
                self.category_manager.edit_category_prompt(display_name)
                self._populate_prompts_tree()  # Обновляем список после редактирования
    
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
    
    def _show_category_context_menu(self, position):
        """Показать контекстное меню для категории"""
        from PySide6.QtWidgets import QMenu, QInputDialog
        
        item = self.categories_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu()
        category_name = item.text()
        
        rename_action = menu.addAction("✏️ Переименовать")
        rename_action.triggered.connect(lambda: self._rename_category(category_name))
        
        edit_prompt_action = menu.addAction("📝 Редактировать промт")
        edit_prompt_action.triggered.connect(lambda: self.category_manager.edit_category_prompt(category_name))
        
        menu.addSeparator()
        
        delete_action = menu.addAction("🗑️ Удалить категорию")
        delete_action.triggered.connect(lambda: self.category_manager.delete_category(category_name))
        
        menu.exec(self.categories_list.mapToGlobal(position))
    
    def _rename_category(self, old_name: str):
        """Переименовать категорию"""
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        
        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать категорию",
            "Новое название:",
            text=old_name
        )
        
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        
        new_name = new_name.strip()
        
        # Проверяем что новое имя не существует
        if new_name in self.categories:
            QMessageBox.warning(self, "Ошибка", f"Категория '{new_name}' уже существует")
            return
        
        # Загружаем старый промт
        old_prompt_key = self.prompt_manager.get_category_prompt_name(old_name)
        prompt_data = self.prompt_manager.load_prompt(old_prompt_key.replace("category_", ""))
        
        # Создаем новый промт
        new_prompt_key = self.prompt_manager.get_category_prompt_name(new_name)
        if prompt_data:
            self.prompt_manager.save_prompt(new_prompt_key.replace("category_", ""), prompt_data)
        
        # Удаляем старый промт
        self.prompt_manager.delete_prompt(old_prompt_key.replace("category_", ""))
        
        # Обновляем список категорий
        idx = self.categories.index(old_name)
        self.categories[idx] = new_name
        
        # Обновляем категорию в блоках документа
        if self.annotation_document:
            for page in self.annotation_document.pages:
                for block in page.blocks:
                    if block.category == old_name:
                        block.category = new_name
        
        # Обновляем UI
        self.category_manager.update_categories_list()
        self._populate_prompts_tree()
        
        if hasattr(self, 'blocks_tree_manager'):
            self.blocks_tree_manager.update_blocks_tree()
        
        QMessageBox.information(self, "Успех", f"Категория переименована: {old_name} → {new_name}")

