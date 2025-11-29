"""
Главное окно приложения
Меню, панели инструментов, интеграция всех компонентов
"""

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QFileDialog, QSpinBox,
                               QComboBox, QTextEdit, QGroupBox, QMessageBox)
from PySide6.QtCore import Qt
from pathlib import Path
from typing import Optional
from app.models import Document, Page, Block, BlockType
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
        self._setup_ui()
        self.setWindowTitle("PDF Annotation Tool")
        self.resize(1200, 800)
    
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
        
        # Кнопки управления файлами
        file_buttons = QHBoxLayout()
        
        self.open_btn = QPushButton("Открыть PDF")
        self.open_btn.clicked.connect(self._open_pdf)
        file_buttons.addWidget(self.open_btn)
        
        self.save_btn = QPushButton("Сохранить разметку")
        self.save_btn.clicked.connect(self._save_annotation)
        file_buttons.addWidget(self.save_btn)
        
        self.load_btn = QPushButton("Загрузить разметку")
        self.load_btn.clicked.connect(self._load_annotation)
        file_buttons.addWidget(self.load_btn)
        
        layout.addLayout(file_buttons)
        
        # Навигация по страницам
        nav_layout = QHBoxLayout()
        
        self.prev_page_btn = QPushButton("◀ Пред.")
        self.prev_page_btn.clicked.connect(self._prev_page)
        nav_layout.addWidget(self.prev_page_btn)
        
        self.page_label = QLabel("Страница: 0 / 0")
        nav_layout.addWidget(self.page_label)
        
        self.next_page_btn = QPushButton("След. ▶")
        self.next_page_btn.clicked.connect(self._next_page)
        nav_layout.addWidget(self.next_page_btn)
        
        layout.addLayout(nav_layout)
        
        # Viewer для страниц
        self.page_viewer = PageViewer()
        self.page_viewer.block_created.connect(self._on_block_created)
        self.page_viewer.block_selected.connect(self._on_block_selected)
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
            self.page_viewer.set_page_image(self.page_images[self.current_page])
            
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
    
    def _on_block_created(self, block: Block):
        """Обработка создания нового блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self.annotation_document.pages[self.current_page]
        current_page_data.blocks.append(block)
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
            self.block_description.setText(block.description)
            self.block_ocr_text.setText(block.ocr_text)
    
    def _on_block_type_changed(self, new_type: str):
        """Изменение типа выбранного блока"""
        # TODO: реализовать изменение типа выбранного блока
        pass
    
    def _on_block_description_changed(self):
        """Изменение описания выбранного блока"""
        # TODO: реализовать изменение описания
        pass
    
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

