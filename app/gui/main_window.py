"""
Главное окно приложения
Меню, панели инструментов, интеграция всех компонентов
"""

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QFileDialog, QSpinBox,
                               QComboBox, QTextEdit, QGroupBox, QMessageBox, QToolBar,
                               QDialog, QDialogButtonBox, QLineEdit, QFormLayout)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from pathlib import Path
from typing import Optional
from app.models import Document, Page, Block, BlockType, BlockSource
from app.pdf_utils import PDFDocument
from app.gui.page_viewer import PageViewer
from app.annotation_io import AnnotationIO
from app.cropping import Cropper
from app.ocr import create_ocr_engine
from app.report_md import MarkdownReporter
from app.auto_segmentation import AutoSegmentation
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
        self.page_viewer.page_changed.connect(self._on_page_changed)
        layout.addWidget(self.page_viewer)
        
        return panel
    
    def _create_right_panel(self) -> QWidget:
        """Создать правую панель с инструментами"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
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
        
        # Описание
        block_layout.addWidget(QLabel("Описание:"))
        self.block_description = QTextEdit()
        self.block_description.setMaximumHeight(100)
        self.block_description.textChanged.connect(self._on_block_description_changed)
        block_layout.addWidget(self.block_description)
        
        # OCR текст
        block_layout.addWidget(QLabel("OCR результат:"))
        self.block_ocr_text = QTextEdit()
        self.block_ocr_text.setReadOnly(True)
        self.block_ocr_text.setMaximumHeight(150)
        block_layout.addWidget(self.block_ocr_text)
        
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
        
        layout.addStretch()
        
        return panel
    
    # ========== Обработчики событий ==========
    
    def _open_pdf(self):
        """Открыть PDF файл"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Открыть PDF", "", "PDF Files (*.pdf)")
        if not file_path:
            return
        
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
    
    def _render_current_page(self):
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
        Обработка завершения рисования блока
        Показываем диалог для ввода параметров блока
        """
        if not self.annotation_document:
            return
        
        # Показываем диалог для ввода параметров
        dialog = BlockPropertiesDialog(self)
        if dialog.exec() == QDialog.Accepted:
            category, block_type = dialog.get_values()
            
            # Получаем размеры страницы
            current_page_data = self.annotation_document.pages[self.current_page]
            page_width = current_page_data.width
            page_height = current_page_data.height
            
            # Создаём блок
            block = Block.create(
                page_index=self.current_page,
                coords_px=(x1, y1, x2, y2),
                page_width=page_width,
                page_height=page_height,
                category=category,
                block_type=block_type,
                source=BlockSource.USER
            )
            
            # Добавляем блок на страницу
            current_page_data.blocks.append(block)
            
            # Обновляем отображение
            self.page_viewer.set_blocks(current_page_data.blocks)
    
    def _on_block_selected(self, block_idx: int):
        """Обработка выбора блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
        if 0 <= block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[block_idx]
            
            # Обновляем UI
            self.block_type_combo.setCurrentText(block.block_type.value)
            self.block_description.setText(block.category)
            self.block_ocr_text.setText(block.ocr_text or "")
    
    def _on_block_type_changed(self, new_type: str):
        """Изменение типа выбранного блока"""
        # TODO: реализовать изменение типа выбранного блока
        pass
    
    def _on_block_description_changed(self):
        """Изменение описания выбранного блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
        if 0 <= self.page_viewer.selected_block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[self.page_viewer.selected_block_idx]
            block.category = self.block_description.toPlainText()
    
    def _on_block_editing(self, block_idx: int):
        """Обработка двойного клика для редактирования блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
        if 0 <= block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[block_idx]
            
            # Показываем диалог редактирования с текущими значениями
            dialog = BlockPropertiesDialog(self)
            dialog.category_edit.setText(block.category)
            dialog.type_combo.setCurrentText(block.block_type.value)
            
            if dialog.exec() == QDialog.Accepted:
                category, block_type = dialog.get_values()
                block.category = category
                block.block_type = block_type
                
                # Обновляем отображение
                self.page_viewer.set_blocks(current_page_data.blocks)
                self._on_block_selected(block_idx)  # перерисовываем UI
    
    def _on_block_deleted(self, block_idx: int):
        """Обработка удаления блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
        if 0 <= block_idx < len(current_page_data.blocks):
            # Удаляем блок
            del current_page_data.blocks[block_idx]
            
            # Очищаем UI
            self.block_description.setText("")
            self.block_type_combo.setCurrentIndex(0)
            self.block_ocr_text.setText("")
            
            # Обновляем отображение
            self.page_viewer.set_blocks(current_page_data.blocks)
            
            QMessageBox.information(self, "Успех", "Блок удалён")
    
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
                QMessageBox.information(self, "Успех", "Разметка загружена")
    
    def _auto_segment_page(self):
        """Автоматическая сегментация текущей страницы"""
        if not self.annotation_document or self.current_page not in self.page_images:
            return
        
        page_img = self.page_images[self.current_page]
        suggested_blocks = self.auto_segmentation.suggest_blocks(page_img)
        
        current_page_data = self.annotation_document.pages[self.current_page]
        current_page_data.blocks.extend(suggested_blocks)
        self.page_viewer.set_blocks(current_page_data.blocks)
        
        QMessageBox.information(self, "Успех", f"Найдено блоков: {len(suggested_blocks)}")
    
    def _run_ocr_all(self):
        """Запустить OCR для всех блоков"""
        if not self.annotation_document:
            return
        
        # TODO: добавить прогресс-бар
        for page in self.annotation_document.pages:
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
                # Обрезаем блок
                crop = page_img.crop((block.x, block.y, 
                                     block.x + block.width, 
                                     block.y + block.height))
                # OCR
                block.ocr_text = self.ocr_engine.recognize(crop)
        
        QMessageBox.information(self, "Успех", "OCR завершён")
    
    def _export_crops(self):
        """Экспорт кропов блоков"""
        if not self.annotation_document:
            return
        
        output_dir = QFileDialog.getExistingDirectory(self, "Выберите папку для экспорта")
        if output_dir:
            cropper = Cropper(output_dir)
            cropper.save_block_crops(self.annotation_document, self.page_images)
            QMessageBox.information(self, "Успех", "Кропы сохранены")
    
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


class BlockPropertiesDialog(QDialog):
    """
    Диалог для ввода свойств блока при ручной разметке или редактировании
    """
    
    def __init__(self, parent=None, title: str = "Свойства блока"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        
        # Создаём форму
        layout = QFormLayout(self)
        
        # Поле для category
        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("Например: Заголовок, Параметры, Спецификация")
        layout.addRow("Категория (описание):", self.category_edit)
        
        # Выбор типа блока
        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value for t in BlockType])
        self.type_combo.setCurrentText(BlockType.TEXT.value)
        layout.addRow("Тип блока:", self.type_combo)
        
        # Кнопки OK/Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
        # Фокус на поле ввода
        self.category_edit.setFocus()
    
    def get_values(self) -> tuple:
        """
        Получить введённые значения
        
        Returns:
            (category: str, block_type: BlockType)
        """
        category = self.category_edit.text().strip()
        block_type = BlockType(self.type_combo.currentText())
        return category, block_type

