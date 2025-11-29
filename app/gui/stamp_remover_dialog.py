"""
Диалог удаления штампов из PDF
Отображает структуру PDF и позволяет удалять элементы
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QLabel, QSplitter,
                               QMessageBox, QFileDialog, QCheckBox)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage
from typing import List, Dict, Optional
from pathlib import Path
import logging
import tempfile

from app.pdf_structure import PDFStructureAnalyzer, PDFStructureModifier, PDFElement, PDFElementType
from app.pdf_utils import PDFDocument

logger = logging.getLogger(__name__)


class StampRemoverDialog(QDialog):
    """Диалог для удаления штампов и других элементов из PDF"""
    
    pdf_cleaned = Signal(str)  # Сигнал с путем к очищенному PDF
    
    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        
        logger.info(f"[StampRemover] Инициализация диалога для: {pdf_path}")
        
        self.pdf_path = pdf_path
        self.analyzer = PDFStructureAnalyzer(pdf_path)
        self.page_elements: Dict[int, List[PDFElement]] = {}
        self.selected_elements: List[PDFElement] = []
        self.cleaned_pdf_path: Optional[str] = None
        self.structure_loaded: bool = False
        
        self.setWindowTitle("Удаление электронных штампов")
        self.resize(1400, 900)
        
        logger.info("[StampRemover] Настройка UI...")
        try:
            self._setup_ui()
            logger.info("[StampRemover] UI настроен")
        except Exception as e:
            logger.error(f"[StampRemover] Ошибка настройки UI: {e}", exc_info=True)
            raise
        
        logger.info("[StampRemover] Инициализация завершена (структура будет загружена при показе)")
    
    def showEvent(self, event):
        """Обработка события показа диалога - загружаем структуру при первом показе"""
        super().showEvent(event)
        
        if not self.structure_loaded:
            logger.info("[StampRemover] Первый показ диалога - загрузка структуры")
            try:
                self._load_structure()
                self.structure_loaded = True
            except Exception as e:
                logger.error(f"[StampRemover] Ошибка загрузки структуры в showEvent: {e}", exc_info=True)
                QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить структуру PDF:\n{e}")
                self.reject()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        logger.debug("[StampRemover] _setup_ui: начало")
        layout = QVBoxLayout(self)
        
        # Заголовок
        header = QLabel(f"<b>Документ:</b> {Path(self.pdf_path).name}")
        layout.addWidget(header)
        
        # Основной сплиттер: слева структура, справа предпросмотр
        splitter = QSplitter(Qt.Horizontal)
        
        # Левая панель: структура
        left_panel = self._create_structure_panel()
        splitter.addWidget(left_panel)
        
        # Правая панель: предпросмотр
        right_panel = self._create_preview_panel()
        splitter.addWidget(right_panel)
        
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        layout.addWidget(splitter)
        
        # Кнопки действий
        button_layout = QHBoxLayout()
        
        self.remove_btn = QPushButton("🗑️ Удалить выбранные")
        self.remove_btn.clicked.connect(self._remove_selected)
        button_layout.addWidget(self.remove_btn)
        
        self.preview_btn = QPushButton("👁️ Предпросмотр")
        self.preview_btn.clicked.connect(self._preview_cleaned)
        button_layout.addWidget(self.preview_btn)
        
        button_layout.addStretch()
        
        self.accept_btn = QPushButton("✓ Применить и загрузить")
        self.accept_btn.clicked.connect(self._accept_and_load)
        button_layout.addWidget(self.accept_btn)
        
        self.cancel_btn = QPushButton("✗ Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _create_structure_panel(self):
        """Создать панель структуры PDF"""
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        layout.addWidget(QLabel("<b>Структура PDF:</b>"))
        
        # Дерево элементов
        self.structure_tree = QTreeWidget()
        self.structure_tree.setHeaderLabels(["Элемент", "Тип"])
        self.structure_tree.setColumnWidth(0, 250)
        self.structure_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.structure_tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.structure_tree)
        
        # Опции фильтрации
        filter_layout = QHBoxLayout()
        
        self.show_annotations_cb = QCheckBox("Аннотации")
        self.show_annotations_cb.setChecked(True)
        self.show_annotations_cb.stateChanged.connect(self._update_tree)
        filter_layout.addWidget(self.show_annotations_cb)
        
        self.show_images_cb = QCheckBox("Изображения")
        self.show_images_cb.setChecked(True)
        self.show_images_cb.stateChanged.connect(self._update_tree)
        filter_layout.addWidget(self.show_images_cb)
        
        self.show_forms_cb = QCheckBox("Контейнеры")
        self.show_forms_cb.setChecked(True)
        self.show_forms_cb.stateChanged.connect(self._update_tree)
        filter_layout.addWidget(self.show_forms_cb)
        
        layout.addLayout(filter_layout)
        
        # Статистика
        self.stats_label = QLabel("Всего элементов: 0")
        layout.addWidget(self.stats_label)
        
        return panel
    
    def _create_preview_panel(self):
        """Создать панель предпросмотра"""
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
        
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        layout.addWidget(QLabel("<b>Предпросмотр:</b>"))
        
        # Скролл-область для изображений
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        self.preview_label = QLabel("Загрузка...")
        self.preview_label.setAlignment(Qt.AlignCenter)
        scroll.setWidget(self.preview_label)
        
        layout.addWidget(scroll)
        
        return panel
    
    def _load_structure(self):
        """Загрузить структуру PDF"""
        try:
            logger.info("[StampRemover] Начало загрузки структуры")
            
            if not self.analyzer.open():
                logger.error("[StampRemover] Не удалось открыть PDF через analyzer")
                QMessageBox.critical(self, "Ошибка", "Не удалось открыть PDF")
                return
            
            # Получаем количество страниц
            page_count = len(self.analyzer.doc) if self.analyzer.doc else 0
            logger.info(f"[StampRemover] Страниц в документе: {page_count}")
            
            # Прогресс для больших файлов
            progress = None
            if page_count > 10:
                logger.info("[StampRemover] Создание прогресс-диалога")
                from PySide6.QtWidgets import QProgressDialog
                progress = QProgressDialog("Анализ структуры PDF...", "Отмена", 0, page_count, self)
                progress.setWindowModality(Qt.WindowModal)
                progress.show()
            
            # Анализируем все страницы
            logger.info("[StampRemover] Начало анализа страниц")
            for page_num in range(page_count):
                if progress and progress.wasCanceled():
                    logger.info("[StampRemover] Анализ отменен пользователем")
                    break
                
                try:
                    logger.debug(f"[StampRemover] Анализ страницы {page_num + 1}/{page_count}")
                    self.page_elements[page_num] = self.analyzer.analyze_page(page_num)
                    logger.debug(f"[StampRemover] Страница {page_num}: найдено {len(self.page_elements[page_num])} элементов")
                except Exception as e:
                    logger.error(f"[StampRemover] Ошибка анализа страницы {page_num}: {e}", exc_info=True)
                    self.page_elements[page_num] = []
                
                if progress:
                    progress.setValue(page_num + 1)
            
            if progress:
                progress.close()
            
            logger.info("[StampRemover] Анализ завершен, закрытие анализатора")
            # Закрываем анализатор
            self.analyzer.close()
            
            logger.info("[StampRemover] Обновление дерева")
            # Обновляем дерево
            self._update_tree()
            
            logger.info("[StampRemover] Отображение предпросмотра")
            # Показываем первую страницу
            self._show_preview_page(0)
            
            logger.info("[StampRemover] Загрузка структуры завершена успешно")
        
        except Exception as e:
            logger.error(f"[StampRemover] Критическая ошибка загрузки структуры: {e}", exc_info=True)
            QMessageBox.critical(self, "Ошибка", f"Не удалось проанализировать PDF:\n{e}")
            self.reject()
    
    def _update_tree(self):
        """Обновить дерево структуры"""
        try:
            logger.debug("[StampRemover] _update_tree: начало")
            self.structure_tree.clear()
            
            show_annots = self.show_annotations_cb.isChecked()
            show_images = self.show_images_cb.isChecked()
            show_forms = self.show_forms_cb.isChecked()
            
            total_count = 0
            
            for page_num in sorted(self.page_elements.keys()):
                elements = self.page_elements[page_num]
                
                # Фильтруем элементы
                filtered = []
                for elem in elements:
                    if elem.element_type == PDFElementType.ANNOTATION and show_annots:
                        filtered.append(elem)
                    elif elem.element_type == PDFElementType.IMAGE and show_images:
                        filtered.append(elem)
                    elif elem.element_type == PDFElementType.FORM and show_forms:
                        filtered.append(elem)
                
                if not filtered:
                    continue
                
                # Создаем узел страницы
                page_item = QTreeWidgetItem(self.structure_tree)
                page_item.setText(0, f"Страница {page_num + 1}")
                page_item.setText(1, f"({len(filtered)} элем.)")
                page_item.setData(0, Qt.UserRole, {"type": "page", "page_num": page_num})
                page_item.setExpanded(True)
                
                # Добавляем элементы
                for elem in filtered:
                    elem_item = QTreeWidgetItem(page_item)
                    elem_item.setText(0, elem.name)
                    elem_item.setText(1, elem.element_type.value)
                    elem_item.setData(0, Qt.UserRole, {"type": "element", "element": elem})
                    
                    total_count += 1
            
            self.stats_label.setText(f"Всего элементов: {total_count}")
            logger.debug(f"[StampRemover] _update_tree: завершено, элементов: {total_count}")
        
        except Exception as e:
            logger.error(f"[StampRemover] Ошибка обновления дерева: {e}", exc_info=True)
            self.stats_label.setText(f"Ошибка: {e}")
    
    def _on_selection_changed(self):
        """Обработка изменения выбора"""
        self.selected_elements.clear()
        
        for item in self.structure_tree.selectedItems():
            data = item.data(0, Qt.UserRole)
            if data and data.get("type") == "element":
                self.selected_elements.append(data["element"])
        
        logger.debug(f"Выбрано элементов: {len(self.selected_elements)}")
    
    def _show_preview_page(self, page_num: int):
        """Показать предпросмотр страницы"""
        try:
            logger.info(f"[StampRemover] Предпросмотр страницы {page_num}")
            pdf_doc = PDFDocument(self.pdf_path)
            
            logger.debug(f"[StampRemover] Открытие PDF для предпросмотра")
            if pdf_doc.open():
                logger.debug(f"[StampRemover] Рендеринг страницы {page_num}")
                image = pdf_doc.render_page(page_num, zoom=1.5)
                
                if image:
                    logger.debug(f"[StampRemover] Изображение получено: {image.size}")
                    logger.debug(f"[StampRemover] Конвертация в RGB")
                    
                    # Конвертируем PIL в QPixmap
                    image_rgb = image.convert("RGB")
                    logger.debug(f"[StampRemover] Получение байтов изображения")
                    
                    data = image_rgb.tobytes("raw", "RGB")
                    logger.debug(f"[StampRemover] Создание QImage ({image.width}x{image.height})")
                    
                    # Создаем QImage с копированием данных
                    qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format_RGB888)
                    # Делаем глубокую копию чтобы данные не исчезли после закрытия pdf_doc
                    qimage = qimage.copy()
                    logger.debug(f"[StampRemover] QImage создан, isNull={qimage.isNull()}")
                    
                    if qimage.isNull():
                        logger.error(f"[StampRemover] QImage NULL!")
                        self.preview_label.setText("Ошибка создания QImage")
                        pdf_doc.close()
                        return
                    
                    logger.debug(f"[StampRemover] Создание QPixmap")
                    pixmap = QPixmap.fromImage(qimage)
                    logger.debug(f"[StampRemover] QPixmap создан, размер: {pixmap.size()}")
                    
                    # Масштабируем для отображения
                    logger.debug(f"[StampRemover] Масштабирование")
                    scaled = pixmap.scaled(800, 1000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    logger.debug(f"[StampRemover] Масштабировано до: {scaled.size()}")
                    
                    logger.debug(f"[StampRemover] Установка pixmap в label")
                    self.preview_label.setPixmap(scaled)
                    logger.info(f"[StampRemover] Предпросмотр отображен успешно")
                else:
                    logger.warning(f"[StampRemover] Не удалось отрендерить страницу {page_num}")
                    self.preview_label.setText("Не удалось отрендерить страницу")
                
                logger.debug(f"[StampRemover] Закрытие PDF документа")
                pdf_doc.close()
                logger.debug(f"[StampRemover] PDF закрыт")
            else:
                logger.error(f"[StampRemover] Не удалось открыть PDF для предпросмотра")
                self.preview_label.setText("Не удалось открыть PDF")
        except Exception as e:
            logger.error(f"[StampRemover] КРИТИЧЕСКАЯ ОШИБКА предпросмотра страницы {page_num}: {e}", exc_info=True)
            try:
                self.preview_label.setText(f"Ошибка предпросмотра:\n{str(e)[:200]}")
            except:
                logger.error(f"[StampRemover] Не удалось даже установить текст ошибки!")
                pass
    
    def _remove_selected(self):
        """Удалить выбранные элементы"""
        if not self.selected_elements:
            QMessageBox.information(self, "Информация", "Выберите элементы для удаления")
            return
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить {len(self.selected_elements)} элемент(ов)?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Создаем временный файл
        temp_dir = tempfile.gettempdir()
        temp_pdf = Path(temp_dir) / f"cleaned_{Path(self.pdf_path).name}"
        
        # Удаляем элементы
        modifier = PDFStructureModifier(self.pdf_path)
        if modifier.open():
            count = modifier.remove_elements(self.selected_elements)
            
            if modifier.save(str(temp_pdf)):
                self.cleaned_pdf_path = str(temp_pdf)
                QMessageBox.information(self, "Успех", f"Удалено {count} элемент(ов)")
                
                # Обновляем предпросмотр
                self.pdf_path = self.cleaned_pdf_path
                self._load_structure()
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось сохранить изменения")
            
            modifier.close()
    
    def _preview_cleaned(self):
        """Предпросмотр очищенного PDF"""
        if not self.cleaned_pdf_path:
            QMessageBox.information(self, "Информация", "Сначала удалите элементы")
            return
        
        # Перезагружаем структуру с очищенного PDF
        self.pdf_path = self.cleaned_pdf_path
        self._load_structure()
    
    def _accept_and_load(self):
        """Применить изменения и загрузить в основное приложение"""
        if not self.cleaned_pdf_path:
            # Если ничего не удаляли, используем исходный файл
            self.pdf_cleaned.emit(self.pdf_path)
        else:
            # Предлагаем сохранить очищенный PDF
            output_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить очищенный PDF",
                str(Path(self.pdf_path).parent / f"{Path(self.pdf_path).stem}_cleaned.pdf"),
                "PDF Files (*.pdf)"
            )
            
            if output_path:
                import shutil
                shutil.copy(self.cleaned_pdf_path, output_path)
                self.pdf_cleaned.emit(output_path)
            else:
                # Используем временный файл
                self.pdf_cleaned.emit(self.cleaned_pdf_path)
        
        self.accept()

