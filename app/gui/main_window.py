"""
Главное окно приложения
Меню, панели инструментов, интеграция всех компонентов
"""

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QFileDialog, QSpinBox,
                               QComboBox, QTextEdit, QGroupBox, QMessageBox, QToolBar,
                               QLineEdit, QTreeWidget, QTreeWidgetItem, QTabWidget)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QActionGroup
from pathlib import Path
from typing import Optional
from app.models import Document, Page, Block, BlockType, BlockSource, PageModel
from app.pdf_utils import PDFDocument
from app.gui.page_viewer import PageViewer
from app.annotation_io import AnnotationIO
from app.cropping import Cropper, export_blocks_by_category
from app.ocr import create_ocr_engine
from app.report_md import MarkdownReporter
from app.auto_segmentation import AutoSegmentation, detect_blocks_from_image
from app.reapply import AnnotationReapplier


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
        
        # Компоненты
        self.ocr_engine = create_ocr_engine("dummy")  # замените на "tesseract" после установки
        self.auto_segmentation = AutoSegmentation()
        
        # Настройка UI
        self._setup_menu()
        self._setup_toolbar()
        self._setup_ui()
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
        
        auto_segment_action = QAction("&Авто-сегментация", self)
        auto_segment_action.setShortcut(QKeySequence("Ctrl+A"))
        auto_segment_action.triggered.connect(self._auto_segment_page)
        tools_menu.addAction(auto_segment_action)
        
        run_ocr_action = QAction("Запустить &OCR", self)
        run_ocr_action.setShortcut(QKeySequence("Ctrl+R"))
        run_ocr_action.triggered.connect(self._run_ocr_all)
        tools_menu.addAction(run_ocr_action)
        
        tools_menu.addSeparator()
        
        export_action = QAction("&Экспорт кропов", self)
        export_action.triggered.connect(self._export_crops)
        tools_menu.addAction(export_action)
        
        md_action = QAction("Генерация &Markdown", self)
        md_action.triggered.connect(self._generate_markdown)
        tools_menu.addAction(md_action)
        
        reapply_action = QAction("&Перенос разметки", self)
        reapply_action.triggered.connect(self._reapply_annotation)
        tools_menu.addAction(reapply_action)
        
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
        self.blocks_tree.itemClicked.connect(self._on_tree_block_clicked)
        self.blocks_tree.itemDoubleClicked.connect(self._on_tree_block_double_clicked)
        self.blocks_tabs.addTab(self.blocks_tree, "Страница")
        
        # Вкладка 2: Категория → Блок → Страница
        self.blocks_tree_by_category = QTreeWidget()
        self.blocks_tree_by_category.setHeaderLabels(["Название", "Тип"])
        self.blocks_tree_by_category.setColumnWidth(0, 150)
        self.blocks_tree_by_category.itemClicked.connect(self._on_tree_block_clicked)
        self.blocks_tree_by_category.itemDoubleClicked.connect(self._on_tree_block_double_clicked)
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
        block_layout.addLayout(cat_layout)
        
        # OCR текст
        block_layout.addWidget(QLabel("OCR результат:"))
        self.block_ocr_text = QTextEdit()
        self.block_ocr_text.setReadOnly(True)
        self.block_ocr_text.setMaximumHeight(100)
        block_layout.addWidget(self.block_ocr_text)
        
        # Кнопка удаления
        self.delete_block_btn = QPushButton("🗑️ Удалить блок")
        self.delete_block_btn.clicked.connect(self._delete_selected_block)
        block_layout.addWidget(self.delete_block_btn)
        
        layout.addWidget(block_group)
        
        # Кнопки действий
        actions_group = QGroupBox("Действия")
        actions_layout = QVBoxLayout(actions_group)
        
        self.auto_segment_btn = QPushButton("Авто-сегментация")
        self.auto_segment_btn.clicked.connect(self._auto_segment_page)
        actions_layout.addWidget(self.auto_segment_btn)
        
        self.run_ocr_btn = QPushButton("Запустить OCR")
        self.run_ocr_btn.clicked.connect(self._run_ocr_all)
        actions_layout.addWidget(self.run_ocr_btn)
        
        self.export_crops_btn = QPushButton("Экспорт кропов")
        self.export_crops_btn.clicked.connect(self._export_crops)
        actions_layout.addWidget(self.export_crops_btn)
        
        self.generate_md_btn = QPushButton("Генерация MD")
        self.generate_md_btn.clicked.connect(self._generate_markdown)
        actions_layout.addWidget(self.generate_md_btn)
        
        self.reapply_btn = QPushButton("Перенос разметки")
        self.reapply_btn.clicked.connect(self._reapply_annotation)
        actions_layout.addWidget(self.reapply_btn)
        
        layout.addWidget(actions_group)
        
        return panel
    
    # ========== Обработчики событий ==========
    
    def _open_pdf(self):
        """Открыть PDF файл"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Открыть PDF", "", "PDF Files (*.pdf)")
        if not file_path:
            return
        
        # Закрываем старый PDF
        if self.pdf_document:
            self.pdf_document.close()
        
        # Очищаем кеш
        self.page_images.clear()
        
        # Открываем PDF
        self.pdf_document = PDFDocument(file_path)
        if not self.pdf_document.open():
            QMessageBox.critical(self, "Ошибка", "Не удалось открыть PDF")
            return
        
        # Инициализируем документ разметки
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
            self.page_viewer.set_page_image(self.page_images[self.current_page], self.current_page)
            
            # Устанавливаем блоки текущей страницы
            current_page_data = self.annotation_document.pages[self.current_page]
            self.page_viewer.set_blocks(current_page_data.blocks)
            
            # Обновляем дерево блоков
            if update_tree:
                self._update_blocks_tree()
    
    def _update_ui(self):
        """Обновить UI элементы"""
        if self.pdf_document:
            self.page_label.setText(f"Страница: {self.current_page + 1} / {self.pdf_document.page_count}")
        else:
            self.page_label.setText("Страница: 0 / 0")
    
    def _prev_page(self):
        """Предыдущая страница"""
        if self.current_page > 0:
            self.current_page -= 1
            self._render_current_page()
            self._update_ui()
    
    def _next_page(self):
        """Следующая страница"""
        if self.pdf_document and self.current_page < self.pdf_document.page_count - 1:
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
        current_page_data = self.annotation_document.pages[self.current_page]
        page_width = current_page_data.width
        page_height = current_page_data.height
        
        # Создаём блок без категории (пользователь задаст потом)
        block = Block.create(
            page_index=self.current_page,
            coords_px=(x1, y1, x2, y2),
            page_width=page_width,
            page_height=page_height,
            category="",
            block_type=block_type,
            source=BlockSource.USER
        )
        
        # Добавляем блок на страницу
        current_page_data.blocks.append(block)
        
        # Обновляем отображение
        self.page_viewer.set_blocks(current_page_data.blocks)
        self._update_blocks_tree()
    
    def _on_block_selected(self, block_idx: int):
        """Обработка выбора блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
        if 0 <= block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[block_idx]
            
            # Обновляем UI свойств
            self.block_type_combo.blockSignals(True)
            self.block_type_combo.setCurrentText(block.block_type.value)
            self.block_type_combo.blockSignals(False)
            
            self.category_edit.blockSignals(True)
            self.category_edit.setText(block.category)
            self.category_edit.blockSignals(False)
            
            self.block_ocr_text.setText(block.ocr_text or "")
            
            # Выделяем в дереве
            self._select_block_in_tree(block_idx)
    
    def _on_block_type_changed(self, new_type: str):
        """Изменение типа выбранного блока"""
        if not self.annotation_document:
            return

        current_page_data = self.annotation_document.pages[self.current_page]
        if self.page_viewer.selected_block_idx is not None and \
           0 <= self.page_viewer.selected_block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[self.page_viewer.selected_block_idx]
            try:
                block.block_type = BlockType(new_type)
                # Перерисовываем Viewer и дерево
                self.page_viewer._redraw_blocks()
                self._update_blocks_tree()
            except ValueError:
                pass
    
    def _on_category_changed(self):
        """Изменение категории выбранного блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
        if self.page_viewer.selected_block_idx is not None and \
           0 <= self.page_viewer.selected_block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[self.page_viewer.selected_block_idx]
            block.category = self.category_edit.text().strip()
            self._update_blocks_tree()
    
    def _update_blocks_tree(self):
        """Обновить дерево блоков со всех страниц, группировка по страницам"""
        self.blocks_tree.clear()
        
        if not self.annotation_document:
            return
        
        # Проходим по всем страницам
        for page in self.annotation_document.pages:
            page_num = page.page_number
            if not page.blocks:
                continue
            
            # Создаём узел страницы
            page_item = QTreeWidgetItem(self.blocks_tree)
            page_item.setText(0, f"Страница {page_num + 1}")
            page_item.setData(0, Qt.UserRole, {"type": "page", "page": page_num})
            page_item.setExpanded(page_num == self.current_page)
            
            # Группируем блоки страницы по категориям
            categories = {}
            for idx, block in enumerate(page.blocks):
                cat = block.category if block.category else "(Без категории)"
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((idx, block))
            
            for cat_name in sorted(categories.keys()):
                cat_item = QTreeWidgetItem(page_item)
                cat_item.setText(0, cat_name)
                cat_item.setData(0, Qt.UserRole, {"type": "category", "page": page_num})
                cat_item.setExpanded(True)
                
                for idx, block in categories[cat_name]:
                    block_item = QTreeWidgetItem(cat_item)
                    block_item.setText(0, f"Блок {idx + 1}")
                    block_item.setText(1, block.block_type.value)
                    block_item.setData(0, Qt.UserRole, {"type": "block", "page": page_num, "idx": idx})
        
        # Обновляем второе дерево (группировка по категориям)
        self._update_blocks_tree_by_category()
    
    def _update_blocks_tree_by_category(self):
        """Обновить дерево блоков со всех страниц, группировка по категориям"""
        self.blocks_tree_by_category.clear()
        
        if not self.annotation_document:
            return
        
        # Собираем все блоки со всех страниц, группируем по категориям
        categories = {}
        for page in self.annotation_document.pages:
            page_num = page.page_number
            for idx, block in enumerate(page.blocks):
                cat = block.category if block.category else "(Без категории)"
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((page_num, idx, block))
        
        # Создаём узлы для каждой категории
        for cat_name in sorted(categories.keys()):
            cat_item = QTreeWidgetItem(self.blocks_tree_by_category)
            cat_item.setText(0, cat_name)
            cat_item.setData(0, Qt.UserRole, {"type": "category"})
            cat_item.setExpanded(True)
            
            for page_num, idx, block in categories[cat_name]:
                block_item = QTreeWidgetItem(cat_item)
                block_item.setText(0, f"Блок {idx + 1} (стр. {page_num + 1})")
                block_item.setText(1, block.block_type.value)
                block_item.setData(0, Qt.UserRole, {"type": "block", "page": page_num, "idx": idx})
    
    def _on_tree_block_clicked(self, item: QTreeWidgetItem, column: int):
        """Клик по блоку в дереве - переход на страницу и выделение"""
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict):
            return
        
        if data.get("type") == "block":
            page_num = data["page"]
            block_idx = data["idx"]
            
            # Всегда обновляем страницу для синхронизации
            self.current_page = page_num
            
            # Рендерим страницу (изображение из кеша если есть)
            if self.current_page in self.page_images:
                self.page_viewer.set_page_image(self.page_images[self.current_page], self.current_page)
            else:
                img = self.pdf_document.render_page(self.current_page)
                if img:
                    self.page_images[self.current_page] = img
                    self.page_viewer.set_page_image(img, self.current_page)
            
            # Устанавливаем блоки текущей страницы
            current_page_data = self.annotation_document.pages[self.current_page]
            self.page_viewer.set_blocks(current_page_data.blocks)
            
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
    
    def _select_block_in_tree(self, block_idx: int):
        """Выделить блок в дереве"""
        # Выделяем в первом дереве (по страницам)
        for i in range(self.blocks_tree.topLevelItemCount()):
            page_item = self.blocks_tree.topLevelItem(i)
            page_data = page_item.data(0, Qt.UserRole)
            if not page_data or page_data.get("page") != self.current_page:
                continue
            
            for j in range(page_item.childCount()):
                cat_item = page_item.child(j)
                for k in range(cat_item.childCount()):
                    block_item = cat_item.child(k)
                    data = block_item.data(0, Qt.UserRole)
                    if data and data.get("idx") == block_idx and data.get("page") == self.current_page:
                        self.blocks_tree.setCurrentItem(block_item)
                        break
        
        # Выделяем во втором дереве (по категориям)
        for i in range(self.blocks_tree_by_category.topLevelItemCount()):
            cat_item = self.blocks_tree_by_category.topLevelItem(i)
            for j in range(cat_item.childCount()):
                block_item = cat_item.child(j)
                data = block_item.data(0, Qt.UserRole)
                if data and data.get("idx") == block_idx and data.get("page") == self.current_page:
                    self.blocks_tree_by_category.setCurrentItem(block_item)
                    return
    
    def _delete_selected_block(self):
        """Удалить выбранный блок"""
        if self.page_viewer.selected_block_idx is not None:
            self._on_block_deleted(self.page_viewer.selected_block_idx)
    
    def _on_block_editing(self, block_idx: int):
        """Обработка двойного клика для редактирования блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
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
        
        current_page_data = self.annotation_document.pages[self.current_page]
        if 0 <= block_idx < len(current_page_data.blocks):
            # Удаляем блок
            del current_page_data.blocks[block_idx]
            
            # Очищаем UI
            self.category_edit.setText("")
            self.block_type_combo.setCurrentIndex(0)
            self.block_ocr_text.setText("")
            self.page_viewer.selected_block_idx = None
            
            # Обновляем отображение
            self.page_viewer.set_blocks(current_page_data.blocks)
            self._update_blocks_tree()
    
    def _on_block_moved(self, block_idx: int, x1: int, y1: int, x2: int, y2: int):
        """Обработка перемещения/изменения размера блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
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
        file_path, _ = QFileDialog.getOpenFileName(self, "Загрузить разметку", "", 
                                                   "JSON Files (*.json)")
        if file_path:
            doc = AnnotationIO.load_annotation(file_path)
            if doc:
                self.annotation_document = doc
                self._render_current_page()
                self._update_blocks_tree()
                QMessageBox.information(self, "Успех", "Разметка загружена")
    
    def _auto_segment_page(self):
        """Автоматическая сегментация текущей страницы"""
        if not self.annotation_document or self.current_page not in self.page_images:
            return
        
        page_img = self.page_images[self.current_page]
        
        # Используем detect_blocks_from_image для обнаружения крупных областей
        detected_blocks = detect_blocks_from_image(page_img, self.current_page, min_area=5000)
        
        current_page_data = self.annotation_document.pages[self.current_page]
        current_page_data.blocks.extend(detected_blocks)
        self.page_viewer.set_blocks(current_page_data.blocks)
        self._update_blocks_tree()
        
        QMessageBox.information(self, "Успех", f"Найдено блоков: {len(detected_blocks)}")
    
    def _run_ocr_all(self):
        """Запустить OCR для всех блоков"""
        if not self.annotation_document:
            return
        
        # TODO: добавить прогресс-бар
        from PySide6.QtWidgets import QProgressDialog
        
        total_blocks = sum(len(p.blocks) for p in self.annotation_document.pages)
        if total_blocks == 0:
            QMessageBox.information(self, "Информация", "Нет блоков для OCR")
            return

        progress = QProgressDialog("Распознавание текста...", "Отмена", 0, total_blocks, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        processed_count = 0
        
        for page in self.annotation_document.pages:
            if progress.wasCanceled():
                break
                
            page_num = page.page_number
            if page_num not in self.page_images:
                # Рендерим страницу если нужно
                img = self.pdf_document.render_page(page_num)
                if img:
                    self.page_images[page_num] = img
            
            page_img = self.page_images.get(page_num)
            if not page_img:
                continue
            
            for block in page.blocks:
                if progress.wasCanceled():
                    break
                
                # Обрезаем блок используя coords_px (x1, y1, x2, y2)
                x1, y1, x2, y2 = block.coords_px
                # Проверяем валидность координат
                if x1 < x2 and y1 < y2:
                    crop = page_img.crop((x1, y1, x2, y2))
                    # OCR
                    block.ocr_text = self.ocr_engine.recognize(crop)
                
                processed_count += 1
                progress.setValue(processed_count)
        
        progress.close()
        QMessageBox.information(self, "Успех", f"OCR завершён. Обработано {processed_count} блоков.")
    
    def _export_crops(self):
        """Экспорт кропов блоков по категориям"""
        if not self.annotation_document:
            return
        
        output_dir = QFileDialog.getExistingDirectory(self, "Выберите папку для экспорта")
        if output_dir:
            # Конвертируем legacy Document в список PageModel
            pages_list = []
            for page in self.annotation_document.pages:
                page_num = page.page_number
                if page_num in self.page_images:
                    page_model = PageModel(
                        page_index=page_num,
                        image=self.page_images[page_num],
                        blocks=page.blocks
                    )
                    pages_list.append(page_model)
            
            # Экспортируем по категориям
            export_blocks_by_category(self.annotation_document.pdf_path, pages_list, output_dir)
            QMessageBox.information(self, "Успех", "Кропы сохранены по категориям")
    
    def _generate_markdown(self):
        """Генерация Markdown отчётов"""
        if not self.annotation_document:
            return
        
        output_dir = QFileDialog.getExistingDirectory(self, "Выберите папку для MD-отчётов")
        if output_dir:
            reporter = MarkdownReporter(output_dir)
            reporter.generate_reports(self.annotation_document)
            QMessageBox.information(self, "Успех", "Markdown отчёты созданы")
    
    def _reapply_annotation(self):
        """Перенос разметки на новый PDF"""
        if not self.annotation_document:
            QMessageBox.warning(self, "Внимание", "Сначала загрузите разметку")
            return
        
        new_pdf_path, _ = QFileDialog.getOpenFileName(self, "Выберите новый PDF", "", 
                                                      "PDF Files (*.pdf)")
        if new_pdf_path:
            reapplier = AnnotationReapplier(self.annotation_document, new_pdf_path)
            new_doc = reapplier.reapply()
            
            if new_doc:
                self.annotation_document = new_doc
                # Переоткрываем PDF
                if self.pdf_document:
                    self.pdf_document.close()
                self.pdf_document = PDFDocument(new_pdf_path)
                self.pdf_document.open()
                self.page_images.clear()
                self.current_page = 0
                self._render_current_page()
                self._update_ui()
                QMessageBox.information(self, "Успех", "Разметка перенесена")

