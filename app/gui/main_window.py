"""
Главное окно приложения
Меню, панели инструментов, интеграция всех компонентов
"""

import logging
import json
import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QFileDialog, QSpinBox,
                               QComboBox, QTextEdit, QGroupBox, QMessageBox, QToolBar,
                               QLineEdit, QTreeWidget, QTreeWidgetItem, QTabWidget,
                               QListWidget, QInputDialog, QMenu, QAbstractItemView, QProgressDialog, QDialog)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QActionGroup
from pathlib import Path
from typing import Optional
from app.models import Document, Page, Block, BlockType, BlockSource, PageModel
from app.pdf_utils import PDFDocument
from app.gui.page_viewer import PageViewer
from app.gui.ocr_manager import OCRManager
from app.gui.blocks_tree_manager import BlocksTreeManager
from app.gui.category_manager import CategoryManager
from app.annotation_io import AnnotationIO
from app.cropping import Cropper
from app.ocr import create_ocr_engine
from app.auto_segmentation import AutoSegmentation

logger = logging.getLogger(__name__)


class MarkerWorker(QThread):
    """Фоновый поток для выполнения разметки Marker"""
    finished = Signal(object)  # Возвращает список обновленных страниц или None
    error = Signal(str)

    def __init__(self, pdf_path, pages, page_images, page_range=None, category=""):
        super().__init__()
        self.pdf_path = pdf_path
        self.pages = pages
        self.page_images = page_images
        self.page_range = page_range
        self.category = category

    def run(self):
        try:
            from app.marker_integration import segment_with_marker
            result = segment_with_marker(self.pdf_path, self.pages, self.page_images, self.page_range, self.category)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """
    Главное окно приложения для аннотирования PDF
    """
    
    def __init__(self):
        super().__init__()
        
        # Данные приложения
        self.pdf_document: Optional[PDFDocument] = None
        self.annotation_document: Optional[Document] = None
        self.current_page: int = 0
        self.page_images: dict = {}  # кеш отрендеренных страниц
        self.categories: list = []  # список пользовательских категорий
        self.active_category: str = ""  # активная категория для новых блоков
        self.page_zoom_states: dict = {}  # зум для каждой страницы
        
        # Компоненты
        self.ocr_engine = create_ocr_engine("dummy")
        self.auto_segmentation = AutoSegmentation()
        
        # Менеджеры (инициализируются после setup_ui)
        self.ocr_manager = None
        self.blocks_tree_manager = None
        self.category_manager = None
        
        # Настройка UI
        self._setup_menu()
        self._setup_toolbar()
        self._setup_ui()
        
        # Инициализация менеджеров после создания UI
        self.ocr_manager = OCRManager(self)
        self.blocks_tree_manager = BlocksTreeManager(self, self.blocks_tree, self.blocks_tree_by_category)
        self.category_manager = CategoryManager(self, self.categories_list)
        
        self.setWindowTitle("PDF Annotation Tool")
        self.resize(1200, 800)
    
    def _setup_menu(self):
        """Настройка меню"""
        menubar = self.menuBar()
        
        # Меню "Файл"
        file_menu = menubar.addMenu("&Файл")
        
        open_action = QAction("&Открыть PDF", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_pdf)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        save_action = QAction("&Сохранить разметку", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._save_annotation)
        file_menu.addAction(save_action)
        
        load_action = QAction("&Загрузить разметку", self)
        load_action.setShortcut(QKeySequence("Ctrl+L"))
        load_action.triggered.connect(self._load_annotation)
        file_menu.addAction(load_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("&Выход", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Меню "Инструменты"
        tools_menu = menubar.addMenu("&Инструменты")
        
        stamp_remove_action = QAction("🗑️ Удалить штампы", self)
        stamp_remove_action.setShortcut(QKeySequence("Ctrl+D"))
        stamp_remove_action.triggered.connect(self._remove_stamps)
        tools_menu.addAction(stamp_remove_action)
        
        tools_menu.addSeparator()
        
        marker_all_action = QAction("&Marker (все стр.)", self)
        marker_all_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
        marker_all_action.triggered.connect(self._marker_segment_all_pages)
        tools_menu.addAction(marker_all_action)
        
        marker_action = QAction("&Marker разметка", self)
        marker_action.setShortcut(QKeySequence("Ctrl+M"))
        marker_action.triggered.connect(self._marker_segment_pdf)
        tools_menu.addAction(marker_action)
        
        tools_menu.addSeparator()
        
        run_ocr_action = QAction("Запустить &OCR", self)
        run_ocr_action.setShortcut(QKeySequence("Ctrl+R"))
        run_ocr_action.triggered.connect(self._run_ocr_all)
        tools_menu.addAction(run_ocr_action)
        
        tools_menu.addSeparator()
        
        export_cat_action = QAction("Экспорт категорий", self)
        export_cat_action.triggered.connect(lambda: self.category_manager.export_categories())
        tools_menu.addAction(export_cat_action)
        
        import_cat_action = QAction("Импорт категорий", self)
        import_cat_action.triggered.connect(lambda: self.category_manager.import_categories())
        tools_menu.addAction(import_cat_action)
        
        # Меню "Вид"
        view_menu = menubar.addMenu("&Вид")
        
        zoom_in_action = QAction("Увеличить", self)
        zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        zoom_in_action.triggered.connect(self._zoom_in)
        view_menu.addAction(zoom_in_action)
        
        zoom_out_action = QAction("Уменьшить", self)
        zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        zoom_out_action.triggered.connect(self._zoom_out)
        view_menu.addAction(zoom_out_action)
        
        zoom_reset_action = QAction("Сбросить масштаб", self)
        zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        zoom_reset_action.triggered.connect(self._zoom_reset)
        view_menu.addAction(zoom_reset_action)
        
        fit_action = QAction("Подогнать к окну", self)
        fit_action.setShortcut(QKeySequence("Ctrl+F"))
        fit_action.triggered.connect(self._fit_to_view)
        view_menu.addAction(fit_action)
        
        view_menu.addSeparator()
        
        clear_page_action = QAction("Очистить разметку страницы", self)
        clear_page_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        clear_page_action.triggered.connect(self._clear_current_page)
        view_menu.addAction(clear_page_action)
    
    def _setup_toolbar(self):
        """Настройка панели инструментов"""
        toolbar = QToolBar("Основная панель")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Кнопки навигации
        self.open_action = QAction("📂 Открыть", self)
        self.open_action.triggered.connect(self._open_pdf)
        toolbar.addAction(self.open_action)
        
        self.save_action = QAction("💾 Сохранить", self)
        self.save_action.triggered.connect(self._save_annotation)
        toolbar.addAction(self.save_action)
        
        self.load_action = QAction("📥 Загрузить", self)
        self.load_action.triggered.connect(self._load_annotation)
        toolbar.addAction(self.load_action)
        
        toolbar.addSeparator()
        
        # Навигация по страницам
        self.prev_action = QAction("◀ Назад", self)
        self.prev_action.triggered.connect(self._prev_page)
        toolbar.addAction(self.prev_action)
        
        self.page_label = QLabel("Страница: 0 / 0")
        toolbar.addWidget(self.page_label)
        
        self.next_action = QAction("Вперед ▶", self)
        self.next_action.triggered.connect(self._next_page)
        toolbar.addAction(self.next_action)
        
        toolbar.addSeparator()
        
        # Выбор типа блока для рисования
        toolbar.addWidget(QLabel("  Тип блока:"))
        
        self.block_type_group = QActionGroup(self)
        self.block_type_group.setExclusive(True)
        
        self.text_action = QAction("📝 Текст", self)
        self.text_action.setCheckable(True)
        self.text_action.setChecked(True)
        self.text_action.setData(BlockType.TEXT)
        self.block_type_group.addAction(self.text_action)
        toolbar.addAction(self.text_action)
        
        self.table_action = QAction("📊 Таблица", self)
        self.table_action.setCheckable(True)
        self.table_action.setData(BlockType.TABLE)
        self.block_type_group.addAction(self.table_action)
        toolbar.addAction(self.table_action)
        
        self.image_action = QAction("🖼️ Картинка", self)
        self.image_action.setCheckable(True)
        self.image_action.setData(BlockType.IMAGE)
        self.block_type_group.addAction(self.image_action)
        toolbar.addAction(self.image_action)
        
        # Текущий выбранный тип
        self.selected_block_type = BlockType.TEXT
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Основной layout
        main_layout = QHBoxLayout(central_widget)
        
        # Левая панель: просмотр страниц
        left_panel = self._create_left_panel()
        main_layout.addWidget(left_panel, stretch=3)
        
        # Правая панель: инструменты и свойства блоков
        right_panel = self._create_right_panel()
        main_layout.addWidget(right_panel, stretch=1)
    
    def _create_left_panel(self) -> QWidget:
        """Создать левую панель с просмотром страниц"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Viewer для страниц
        self.page_viewer = PageViewer()
        self.page_viewer.blockDrawn.connect(self._on_block_drawn)
        self.page_viewer.block_selected.connect(self._on_block_selected)
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
        
        # Группа: список блоков со всех страниц
        blocks_group = QGroupBox("Все блоки")
        blocks_layout = QVBoxLayout(blocks_group)
        
        # Вкладки
        self.blocks_tabs = QTabWidget()
        
        # Вкладка 1: Страница → Категория → Блок
        self.blocks_tree = QTreeWidget()
        self.blocks_tree.setHeaderLabels(["Название", "Тип"])
        self.blocks_tree.setColumnWidth(0, 150)
        self.blocks_tree.setSortingEnabled(True)
        self.blocks_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.blocks_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.blocks_tree.customContextMenuRequested.connect(lambda pos: self.blocks_tree_manager.on_tree_context_menu(pos))
        self.blocks_tree.itemClicked.connect(self._on_tree_block_clicked)
        self.blocks_tree.itemDoubleClicked.connect(self._on_tree_block_double_clicked)
        self.blocks_tree.installEventFilter(self)
        self.blocks_tabs.addTab(self.blocks_tree, "Страница")
        
        # Вкладка 2: Категория → Блок → Страница
        self.blocks_tree_by_category = QTreeWidget()
        self.blocks_tree_by_category.setHeaderLabels(["Название", "Тип"])
        self.blocks_tree_by_category.setColumnWidth(0, 150)
        self.blocks_tree_by_category.setSortingEnabled(True)
        self.blocks_tree_by_category.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.blocks_tree_by_category.setContextMenuPolicy(Qt.CustomContextMenu)
        self.blocks_tree_by_category.customContextMenuRequested.connect(lambda pos: self.blocks_tree_manager.on_tree_context_menu(pos))
        self.blocks_tree_by_category.itemClicked.connect(self._on_tree_block_clicked)
        self.blocks_tree_by_category.itemDoubleClicked.connect(self._on_tree_block_double_clicked)
        self.blocks_tree_by_category.installEventFilter(self)
        self.blocks_tabs.addTab(self.blocks_tree_by_category, "Категория")
        
        blocks_layout.addWidget(self.blocks_tabs)
        
        layout.addWidget(blocks_group)
        
        # Группа: свойства выбранного блока
        block_group = QGroupBox("Свойства блока")
        block_layout = QVBoxLayout(block_group)
        
        # Тип блока
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Тип:"))
        self.block_type_combo = QComboBox()
        self.block_type_combo.addItems([t.value for t in BlockType])
        self.block_type_combo.currentTextChanged.connect(self._on_block_type_changed)
        type_layout.addWidget(self.block_type_combo)
        block_layout.addLayout(type_layout)
        
        # Категория
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("Категория:"))
        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("Введите категорию...")
        self.category_edit.editingFinished.connect(self._on_category_changed)
        cat_layout.addWidget(self.category_edit)
        
        # Кнопка добавления категории
        self.add_category_btn = QPushButton("➕")
        self.add_category_btn.setMaximumWidth(30)
        self.add_category_btn.setToolTip("Добавить новую категорию")
        self.add_category_btn.clicked.connect(lambda: self.category_manager.add_category())
        cat_layout.addWidget(self.add_category_btn)
        block_layout.addLayout(cat_layout)
        
        # Список категорий
        block_layout.addWidget(QLabel("Категории:"))
        self.categories_list = QListWidget()
        self.categories_list.setMaximumHeight(80)
        self.categories_list.itemClicked.connect(lambda item: self.category_manager.on_category_clicked(item))
        block_layout.addWidget(self.categories_list)
        
        layout.addWidget(block_group)
        
        # Кнопки действий
        actions_group = QGroupBox("Действия")
        actions_layout = QVBoxLayout(actions_group)
        
        self.remove_stamps_btn = QPushButton("🗑️ Удалить штампы")
        self.remove_stamps_btn.clicked.connect(self._remove_stamps)
        actions_layout.addWidget(self.remove_stamps_btn)
        
        actions_layout.addWidget(QLabel(""))  # Разделитель
        
        self.marker_all_btn = QPushButton("Marker (все стр.)")
        self.marker_all_btn.clicked.connect(self._marker_segment_all_pages)
        actions_layout.addWidget(self.marker_all_btn)
        
        self.marker_segment_btn = QPushButton("Marker разметка")
        self.marker_segment_btn.clicked.connect(self._marker_segment_pdf)
        actions_layout.addWidget(self.marker_segment_btn)
        
        actions_layout.addWidget(QLabel(""))  # Разделитель
        
        self.run_ocr_btn = QPushButton("Запустить OCR")
        self.run_ocr_btn.clicked.connect(self._run_ocr_all)
        actions_layout.addWidget(self.run_ocr_btn)
        
        layout.addWidget(actions_group)
        
        return panel
    
    # ========== Вспомогательные методы ==========
    
    def _get_or_create_page(self, page_num: int) -> Page:
        """Получить страницу или создать новую если её нет"""
        if not self.annotation_document:
            return None
        
        # Расширяем список страниц если нужно
        while len(self.annotation_document.pages) <= page_num:
            if self.pdf_document:
                dims = self.pdf_document.get_page_dimensions(len(self.annotation_document.pages))
                if dims:
                    page = Page(page_number=len(self.annotation_document.pages), 
                              width=dims[0], height=dims[1])
                    self.annotation_document.pages.append(page)
                else:
                    # Если не удалось получить размеры, используем дефолтные
                    page = Page(page_number=len(self.annotation_document.pages), 
                              width=595, height=842)
                    self.annotation_document.pages.append(page)
        
        return self.annotation_document.pages[page_num]
    
    # ========== Обработчики событий ==========
    
    def _open_pdf(self):
        """Открыть PDF файл"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Открыть PDF", "", "PDF Files (*.pdf)")
        if not file_path:
            return
        
        # Открываем PDF напрямую (быстро)
        self._load_cleaned_pdf(file_path)
    
    def _load_cleaned_pdf(self, file_path: str, keep_annotation: bool = False):
        """Загрузить PDF (исходный или очищенный) в основное приложение"""
        # Закрываем старый PDF
        if self.pdf_document:
            self.pdf_document.close()
        
        # Очищаем кеш
        self.page_images.clear()
        self.page_zoom_states.clear()
        
        # Открываем PDF
        self.pdf_document = PDFDocument(file_path)
        if not self.pdf_document.open():
            QMessageBox.critical(self, "Ошибка", "Не удалось открыть PDF")
            return
        
        # Инициализируем документ разметки (если не сохраняем существующий)
        if not keep_annotation:
            self.annotation_document = Document(pdf_path=file_path)
            for page_num in range(self.pdf_document.page_count):
                dims = self.pdf_document.get_page_dimensions(page_num)
                if dims:
                    page = Page(page_number=page_num, width=dims[0], height=dims[1])
                    self.annotation_document.pages.append(page)
        
        # Отображаем первую страницу
        self.current_page = 0
        self._render_current_page()
        self._update_ui()
        self.category_manager.extract_categories_from_document()
    
    def _render_current_page(self, update_tree: bool = True):
        """Отрендерить текущую страницу"""
        if not self.pdf_document:
            return
        
        # Рендерим если ещё не в кеше
        if self.current_page not in self.page_images:
            img = self.pdf_document.render_page(self.current_page)
            if img:
                self.page_images[self.current_page] = img
        
        # Отображаем
        if self.current_page in self.page_images:
            self.page_viewer.set_page_image(self.page_images[self.current_page], self.current_page, reset_zoom=False)
            
            # Восстанавливаем зум для этой страницы
            if self.current_page in self.page_zoom_states:
                # Страница уже была посещена - восстанавливаем её зум
                saved_transform, saved_zoom = self.page_zoom_states[self.current_page]
                self.page_viewer.setTransform(saved_transform)
                self.page_viewer.zoom_factor = saved_zoom
            elif self.page_zoom_states:
                # Новая страница - наследуем зум с последней посещенной
                last_page = max(self.page_zoom_states.keys())
                saved_transform, saved_zoom = self.page_zoom_states[last_page]
                self.page_viewer.setTransform(saved_transform)
                self.page_viewer.zoom_factor = saved_zoom
            else:
                # Первая страница - используем дефолтный зум
                self.page_viewer.resetTransform()
                self.page_viewer.zoom_factor = 1.0
            
            # Устанавливаем блоки текущей страницы
            current_page_data = self._get_or_create_page(self.current_page)
            self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
            
            # Обновляем дерево блоков
            if update_tree:
                self.blocks_tree_manager.update_blocks_tree()
    
    def _update_ui(self):
        """Обновить UI элементы"""
        if self.pdf_document:
            self.page_label.setText(f"Страница: {self.current_page + 1} / {self.pdf_document.page_count}")
        else:
            self.page_label.setText("Страница: 0 / 0")
    
    def _prev_page(self):
        """Предыдущая страница"""
        if self.current_page > 0:
            # Сохраняем зум текущей страницы
            self.page_zoom_states[self.current_page] = (
                self.page_viewer.transform(),
                self.page_viewer.zoom_factor
            )
            
            self.current_page -= 1
            self._render_current_page()
            self._update_ui()
    
    def _next_page(self):
        """Следующая страница"""
        if self.pdf_document and self.current_page < self.pdf_document.page_count - 1:
            # Сохраняем зум текущей страницы
            self.page_zoom_states[self.current_page] = (
                self.page_viewer.transform(),
                self.page_viewer.zoom_factor
            )
            
            self.current_page += 1
            self._render_current_page()
            self._update_ui()
    
    def _on_block_drawn(self, x1: int, y1: int, x2: int, y2: int):
        """
        Обработка завершения рисования блока.
        Блок создаётся сразу с типом, выбранным на тулбаре.
        """
        if not self.annotation_document:
            return
        
        # Получаем текущий выбранный тип из тулбара
        checked_action = self.block_type_group.checkedAction()
        block_type = checked_action.data() if checked_action else BlockType.TEXT
        
        # Получаем размеры страницы
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        page_width = current_page_data.width
        page_height = current_page_data.height
        
        # Создаём блок с активной категорией (если выбрана)
        block = Block.create(
            page_index=self.current_page,
            coords_px=(x1, y1, x2, y2),
            page_width=page_width,
            page_height=page_height,
            category=self.active_category,
            block_type=block_type,
            source=BlockSource.USER
        )
        
        # Добавляем блок на страницу
        current_page_data.blocks.append(block)
        
        # Обновляем отображение
        self.page_viewer.set_blocks(current_page_data.blocks)
        self.blocks_tree_manager.update_blocks_tree()
    
    def _on_block_selected(self, block_idx: int):
        """Обработка выбора блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data or not (0 <= block_idx < len(current_page_data.blocks)):
            return
        
        block = current_page_data.blocks[block_idx]
        
        # Обновляем UI свойств
        self.block_type_combo.blockSignals(True)
        self.block_type_combo.setCurrentText(block.block_type.value)
        self.block_type_combo.blockSignals(False)
        
        self.category_edit.blockSignals(True)
        self.category_edit.setText(block.category)
        self.category_edit.blockSignals(False)
        
        # Выделяем в дереве
        self.blocks_tree_manager.select_block_in_tree(block_idx)
    
    def _on_block_type_changed(self, new_type: str):
        """Изменение типа выбранного блока"""
        if not self.annotation_document:
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if self.page_viewer.selected_block_idx is not None and \
           0 <= self.page_viewer.selected_block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[self.page_viewer.selected_block_idx]
            try:
                block.block_type = BlockType(new_type)
                # Перерисовываем Viewer и дерево
                self.page_viewer._redraw_blocks()
                self.blocks_tree_manager.update_blocks_tree()
            except ValueError:
                pass
    
    def _on_category_changed(self):
        """Изменение категории выбранного блока"""
        category = self.category_edit.text().strip()
        
        # Устанавливаем как активную категорию
        self.active_category = category
        
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if self.page_viewer.selected_block_idx is not None and \
           0 <= self.page_viewer.selected_block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[self.page_viewer.selected_block_idx]
            block.category = category
            self.blocks_tree_manager.update_blocks_tree()
    
    def _add_category(self):
        """Добавить новую категорию в список"""
        # Если есть текст в поле, используем его
        text = self.category_edit.text().strip()
        if not text:
            # Иначе открываем диалог
            text, ok = QInputDialog.getText(self, "Новая категория", "Введите название категории:")
            if not ok or not text.strip():
                return
            text = text.strip()
        
        # Добавляем если ещё нет
        if text and text not in self.categories:
            self.categories.append(text)
            self._update_categories_list()
        
        # Устанавливаем как активную категорию
        self.active_category = text
        
        # Применяем к выбранному блоку
        if self.page_viewer.selected_block_idx is not None:
            self.category_manager.apply_category_to_selected_block(text)
    
    def _on_tree_block_clicked(self, item: QTreeWidgetItem, column: int):
        """Клик по блоку в дереве - переход на страницу и выделение"""
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict):
            return
        
        if data.get("type") == "block":
            page_num = data["page"]
            block_idx = data["idx"]
            
            # Сохраняем зум текущей страницы перед переходом
            if self.current_page != page_num:
                self.page_zoom_states[self.current_page] = (
                    self.page_viewer.transform(),
                    self.page_viewer.zoom_factor
                )
            
            # Всегда обновляем страницу для синхронизации
            self.current_page = page_num
            
            # Рендерим страницу (изображение из кеша если есть)
            if self.current_page in self.page_images:
                self.page_viewer.set_page_image(self.page_images[self.current_page], self.current_page, reset_zoom=False)
            else:
                img = self.pdf_document.render_page(self.current_page)
                if img:
                    self.page_images[self.current_page] = img
                    self.page_viewer.set_page_image(img, self.current_page, reset_zoom=False)
            
            # Восстанавливаем зум
            if self.current_page in self.page_zoom_states:
                saved_transform, saved_zoom = self.page_zoom_states[self.current_page]
                self.page_viewer.setTransform(saved_transform)
                self.page_viewer.zoom_factor = saved_zoom
            elif self.page_zoom_states:
                last_page = max(self.page_zoom_states.keys())
                saved_transform, saved_zoom = self.page_zoom_states[last_page]
                self.page_viewer.setTransform(saved_transform)
                self.page_viewer.zoom_factor = saved_zoom
            
            # Устанавливаем блоки текущей страницы
            current_page_data = self._get_or_create_page(self.current_page)
            self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
            
            # Вписываем страницу в область просмотра
            self.page_viewer.fit_to_view()
            
            # Выделяем нужный блок
            self.page_viewer.selected_block_idx = block_idx
            self.page_viewer._redraw_blocks()
            
            self._update_ui()
            self._on_block_selected(block_idx)
    
    def _on_tree_block_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Двойной клик - редактирование категории"""
        data = item.data(0, Qt.UserRole)
        if data and isinstance(data, dict) and data.get("type") == "block":
            self.category_edit.setFocus()
            self.category_edit.selectAll()
    
    def _delete_selected_block(self):
        """Удалить выбранный блок"""
        if self.page_viewer.selected_block_idx is not None:
            self._on_block_deleted(self.page_viewer.selected_block_idx)
    
    def _on_block_editing(self, block_idx: int):
        """Обработка двойного клика для редактирования блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            # Выбираем блок и фокусируемся на поле категории
            self.page_viewer.selected_block_idx = block_idx
            self._on_block_selected(block_idx)
            self.category_edit.setFocus()
            self.category_edit.selectAll()
    
    def _on_block_deleted(self, block_idx: int):
        """Обработка удаления блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            # Сначала сбрасываем выбор во вьюере, чтобы сигналы от UI не применились к "новому" блоку по старому индексу
            self.page_viewer.selected_block_idx = None
            
            # Удаляем блок
            del current_page_data.blocks[block_idx]
            
            # Очищаем UI с блокировкой сигналов
            self.category_edit.blockSignals(True)
            self.category_edit.setText("")
            self.category_edit.blockSignals(False)
            
            self.block_type_combo.blockSignals(True)
            self.block_type_combo.setCurrentIndex(0)
            self.block_type_combo.blockSignals(False)
            
            # Обновляем отображение
            self.page_viewer.set_blocks(current_page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
    
    def _on_block_moved(self, block_idx: int, x1: int, y1: int, x2: int, y2: int):
        """Обработка перемещения/изменения размера блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[block_idx]
            # Обновляем координаты с пересчетом нормализованных
            block.update_coords_px((x1, y1, x2, y2), 
                                 current_page_data.width, 
                                 current_page_data.height)
    
    def _on_page_changed(self, new_page: int):
        """Обработка запроса смены страницы от viewer"""
        if self.pdf_document and 0 <= new_page < self.pdf_document.page_count:
            self.current_page = new_page
            self._render_current_page()
            self._update_ui()
    
    def keyPressEvent(self, event):
        """Обработка нажатия клавиш в главном окне"""
        if event.key() == Qt.Key_Left:
            self._prev_page()
            return
        elif event.key() == Qt.Key_Right:
            self._next_page()
            return
        
        super().keyPressEvent(event)
    
    def eventFilter(self, obj, event):
        """Обработка событий для деревьев блоков"""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        
        if hasattr(self, 'blocks_tree') and hasattr(self, 'blocks_tree_by_category') and \
           obj in (self.blocks_tree, self.blocks_tree_by_category):
            if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key_Delete:
                    current_item = obj.currentItem()
                    if current_item:
                        data = current_item.data(0, Qt.UserRole)
                        if data and isinstance(data, dict) and data.get("type") == "block":
                            page_num = data["page"]
                            block_idx = data["idx"]
                            
                            # Переключаемся на нужную страницу
                            self.current_page = page_num
                            
                            # Рендерим страницу
                            if self.current_page in self.page_images:
                                self.page_viewer.set_page_image(self.page_images[self.current_page], self.current_page, reset_zoom=False)
                            else:
                                img = self.pdf_document.render_page(self.current_page)
                                if img:
                                    self.page_images[self.current_page] = img
                                    self.page_viewer.set_page_image(img, self.current_page, reset_zoom=False)
                            
                            # Устанавливаем блоки текущей страницы
                            current_page_data = self._get_or_create_page(self.current_page)
                            self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
                            
                            # Удаляем блок
                            self._on_block_deleted(block_idx)
                            
                            self._update_ui()
                            return True
        
        return super().eventFilter(obj, event)
    
    def _zoom_in(self):
        """Увеличить масштаб"""
        if hasattr(self.page_viewer, 'scale'):
            self.page_viewer.scale(1.15, 1.15)
            self.page_viewer.zoom_factor *= 1.15
    
    def _zoom_out(self):
        """Уменьшить масштаб"""
        if hasattr(self.page_viewer, 'scale'):
            self.page_viewer.scale(1/1.15, 1/1.15)
            self.page_viewer.zoom_factor /= 1.15
    
    def _zoom_reset(self):
        """Сбросить масштаб"""
        if hasattr(self.page_viewer, 'reset_zoom'):
            self.page_viewer.reset_zoom()
    
    def _fit_to_view(self):
        """Подогнать к окну"""
        if hasattr(self.page_viewer, 'fit_to_view'):
            self.page_viewer.fit_to_view()
    
    def _save_annotation(self):
        """Сохранить разметку в JSON"""
        if not self.annotation_document:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Сохранить разметку", "blocks.json", 
                                                   "JSON Files (*.json)")
        if file_path:
            AnnotationIO.save_annotation(self.annotation_document, file_path)
            QMessageBox.information(self, "Успех", "Разметка сохранена")
    
    def _load_annotation(self):
        """Загрузить разметку из JSON"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Загрузить разметку", "", "JSON Files (*.json)")
        if not file_path:
            return
        
        loaded_doc = AnnotationIO.load_annotation(file_path)
        if loaded_doc:
            self.annotation_document = loaded_doc
            
            pdf_path = loaded_doc.pdf_path
            if Path(pdf_path).exists():
                self._load_cleaned_pdf(pdf_path, keep_annotation=True)
            else:
                # PDF не найден, но блоки все равно нужно отобразить если PDF уже загружен
                if self.pdf_document:
                    self.current_page = 0
                    self._render_current_page()
                    self._update_ui()
            
            self.blocks_tree_manager.update_blocks_tree()
            self.category_manager.extract_categories_from_document()
            QMessageBox.information(self, "Успех", "Разметка загружена")
    
    def _marker_segment_pdf(self):
        """Разметка текущей страницы PDF с помощью Marker (в фоне)"""
        self._run_marker_worker(page_range=[self.current_page], show_success=False)

    def _marker_segment_all_pages(self):
        """Разметка всех страниц PDF с помощью Marker (в фоне)"""
        self._run_marker_worker(page_range=None, show_success=True)

    def _run_marker_worker(self, page_range=None, show_success=True):
        """Запуск Marker в фоновом потоке"""
        if not self.annotation_document or not self.pdf_document:
            QMessageBox.warning(self, "Внимание", "Сначала откройте PDF")
            return
        
        # Подготовка данных (рендер нужных страниц)
        # Для текущей страницы рендерим сразу
        if page_range and len(page_range) == 1:
            page_num = page_range[0]
            if page_num not in self.page_images:
                img = self.pdf_document.render_page(page_num)
                if img:
                    self.page_images[page_num] = img
        else:
            # Для всех страниц - рендерим недостающие
            # Это может занять время, но лучше сделать тут или в треде?
            # Marker все равно требует картинки.
            # Если страниц много, рендер может заблокировать UI.
            # Но Marker worker принимает page_images.
            # Давайте рендерить по мере необходимости внутри worker?
            # Нет, marker_integration ожидает dict с images.
            # Быстрый фикс: рендерим недостающие здесь с прогрессом, или пусть worker рендерит?
            # У marker_integration нет доступа к методам рендера PDFDocument (только path).
            # Оставим рендер здесь, но с processEvents если нужно.
            # Для ускорения UI просто запустим как есть, предполагая что пользователь подождет рендера.
            pass

        # Диалог прогресса (интерактивный спинер)
        self._progress_dialog = QProgressDialog("Marker анализирует PDF...", "Отмена", 0, 0, self)
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setCancelButton(None)  # Нельзя отменить (пока)
        self._progress_dialog.show()

        # Создаем и запускаем воркер
        self._worker = MarkerWorker(
            self.pdf_document.pdf_path,
            self.annotation_document.pages,
            self.page_images,
            page_range=page_range,
            category=self.active_category
        )
        
        self._worker.finished.connect(lambda result: self._on_marker_finished(result, show_success))
        self._worker.error.connect(self._on_marker_error)
        self._worker.finished.connect(self._progress_dialog.close)
        self._worker.error.connect(self._progress_dialog.close)
        
        self._worker.start()

    def _on_marker_finished(self, updated_pages, show_success):
        """Обработка завершения Marker"""
        if updated_pages:
            self.annotation_document.pages = updated_pages
            
            # Сохраняем текущий зум
            saved_transform = self.page_viewer.transform()
            saved_zoom = self.page_viewer.zoom_factor
            
            self._render_current_page()
            self.blocks_tree_manager.update_blocks_tree()
            self.category_manager.extract_categories_from_document()
            
            # Восстанавливаем зум
            self.page_viewer.setTransform(saved_transform)
            self.page_viewer.zoom_factor = saved_zoom
            
            if show_success:
                total_blocks = sum(len(p.blocks) for p in updated_pages)
                QMessageBox.information(self, "Успех", f"Marker завершен. Всего блоков: {total_blocks}")
        else:
            QMessageBox.warning(self, "Ошибка", "Marker не смог обработать PDF")

    def _on_marker_error(self, error_msg):
        """Обработка ошибки Marker"""
        QMessageBox.critical(self, "Ошибка", f"Ошибка Marker: {error_msg}")
    
    def _run_ocr_all(self):
        """Запустить OCR для всех блоков"""
        self.ocr_manager.run_ocr_all()

        """Запустить LocalVLM OCR для блоков с сохранением результатов в папку"""
        from PySide6.QtWidgets import QProgressDialog
        from app.ocr import create_ocr_engine, generate_structured_markdown
        from app.annotation_io import AnnotationIO
        
        try:
            ocr_engine = create_ocr_engine("local_vlm", api_base=api_base, model_name=model_name)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка LocalVLM OCR", f"Не удалось инициализировать:\n{e}")
            return
            
        total_blocks = sum(len(p.blocks) for p in self.annotation_document.pages)
        if total_blocks == 0:
            QMessageBox.information(self, "Информация", "Нет блоков для OCR")
            return

        progress = QProgressDialog(f"Распознавание блоков через {model_name}...", "Отмена", 0, total_blocks, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        processed_count = 0
        
        for page in self.annotation_document.pages:
            if progress.wasCanceled():
                break
                
            page_num = page.page_number
            if page_num not in self.page_images:
                img = self.pdf_document.render_page(page_num)
                if img:
                    self.page_images[page_num] = img
            
            page_img = self.page_images.get(page_num)
            if not page_img:
                continue
            
            for block in page.blocks:
                if progress.wasCanceled():
                    break
                
                x1, y1, x2, y2 = block.coords_px
                if x1 >= x2 or y1 >= y2:
                    processed_count += 1
                    progress.setValue(processed_count)
                    continue
                
                crop = page_img.crop((x1, y1, x2, y2))
                
                try:
                    # Сохраняем кроп
                    crop_filename = f"page{page_num}_block{block.id}.png"
                    crop_path = crops_dir / crop_filename
                    crop.save(crop_path, "PNG")
                    block.image_file = str(crop_path)
                    
                    if block.block_type == BlockType.IMAGE:
                        from app.ocr import load_prompt
                        image_prompt = load_prompt("ocr_image_description.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=image_prompt)
                    elif block.block_type == BlockType.TABLE:
                        from app.ocr import load_prompt
                        table_prompt = load_prompt("ocr_table.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=table_prompt) if table_prompt else ocr_engine.recognize(crop)
                    elif block.block_type == BlockType.TEXT:
                        from app.ocr import load_prompt
                        text_prompt = load_prompt("ocr_text.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=text_prompt) if text_prompt else ocr_engine.recognize(crop)
                        
                except Exception as e:
                    logger.error(f"Error OCR block {block.id}: {e}")
                    block.ocr_text = f"[Error: {e}]"
                
                processed_count += 1
                progress.setValue(processed_count)
        
        progress.close()
        
        # 3. Сохраняем разметку JSON
        json_path = output_dir / "annotation.json"
        AnnotationIO.save_annotation(self.annotation_document, str(json_path))
        logger.info(f"Разметка сохранена: {json_path}")
        
        # 4. Генерируем Markdown
        md_path = output_dir / "document.md"
        generate_structured_markdown(self.annotation_document.pages, str(md_path))
        logger.info(f"Markdown сохранен: {md_path}")
        
        pdf_name = Path(self.annotation_document.pdf_path).name
        QMessageBox.information(
            self, 
            "Готово", 
            f"OCR завершен!\n\n"
            f"Результаты сохранены в:\n{output_dir}\n\n"
            f"• {pdf_name}\n"
            f"• annotation.json\n"
            f"• crops/\n"
            f"• document.md"
        )
    
    
    def _generate_structured_markdown(self):
        """Генерация структурированного Markdown документа из размеченных блоков"""
        if not self.annotation_document:
            return
        
        from app.ocr import generate_structured_markdown
        
        # Выбираем путь для сохранения
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить структурированный документ",
            "recognized_document.md",
            "Markdown Files (*.md)"
        )
        
        if not output_path:
            return
        
        try:
            result_path = generate_structured_markdown(
                self.annotation_document.pages,
                output_path
            )
            
            QMessageBox.information(
                self,
                "Успех",
                f"Структурированный Markdown документ создан:\n{result_path}\n\n"
                f"Изображения сохранены с кропами и описаниями."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Ошибка генерации структурированного markdown:\n{e}"
            )
    
    def _remove_stamps(self):
        """Удаление электронных штампов из PDF"""
        logger.info("=" * 60)
        logger.info("[MainWindow] Запуск удаления штампов")
        logger.info("=" * 60)
        
        if not self.pdf_document or not self.annotation_document:
            logger.warning("[MainWindow] PDF не открыт")
            QMessageBox.warning(self, "Внимание", "Сначала откройте PDF")
            return
        
        try:
            logger.info("[MainWindow] Импорт StampRemoverDialog")
            from app.gui.stamp_remover_dialog import StampRemoverDialog
            
            current_pdf_path = self.annotation_document.pdf_path
            logger.info(f"[MainWindow] Текущий PDF: {current_pdf_path}")
            
            logger.info("[MainWindow] Создание диалога удаления штампов")
            dialog = StampRemoverDialog(current_pdf_path, self)
            
            logger.info("[MainWindow] Открытие диалога")
            if dialog.exec() == QDialog.Accepted:
                logger.info("[MainWindow] Диалог принят")
                # Получаем путь к очищенному PDF
                if dialog.cleaned_pdf_path:
                    logger.info(f"[MainWindow] Очищенный PDF: {dialog.cleaned_pdf_path}")
                    # Перезагружаем PDF
                    reply = QMessageBox.question(
                        self,
                        "Перезагрузить PDF",
                        "Загрузить очищенный PDF?\n\n"
                        "Все несохраненные изменения будут потеряны.",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    
                    if reply == QMessageBox.Yes:
                        logger.info("[MainWindow] Перезагрузка очищенного PDF")
                        self._load_cleaned_pdf(dialog.cleaned_pdf_path)
                else:
                    logger.info("[MainWindow] Изменений не было")
                    QMessageBox.information(self, "Информация", "Изменений не было")
            else:
                logger.info("[MainWindow] Диалог отменен")
        
        except Exception as e:
            logger.error(f"[MainWindow] Критическая ошибка удаления штампов: {e}", exc_info=True)
            QMessageBox.critical(self, "Ошибка", f"Ошибка удаления штампов:\n{e}")
    def _clear_current_page(self):
        """Очистить все блоки с текущей страницы"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data or not current_page_data.blocks:
            QMessageBox.information(self, "Информация", "На странице нет блоков")
            return
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить все {len(current_page_data.blocks)} блоков со страницы {self.current_page + 1}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            current_page_data.blocks.clear()
            self.page_viewer.set_blocks([])
            self.blocks_tree_manager.update_blocks_tree()
            QMessageBox.information(self, "Успех", "Разметка страницы очищена")
