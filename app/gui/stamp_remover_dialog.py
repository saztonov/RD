"""
Диалог удаления штампов из PDF
Отображает структуру PDF и позволяет удалять элементы
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QLabel, QSplitter,
                               QMessageBox, QFileDialog, QCheckBox, QSpinBox, QWidget)
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from typing import List, Dict, Optional, Set
from pathlib import Path
import logging
import tempfile

from app.pdf_structure import PDFStructureAnalyzer, PDFStructureModifier, PDFElement, PDFElementType
from app.pdf_utils import PDFDocument
from app.gui.stamp_preview_manager import StampPreviewManager
from app.gui.stamp_structure_manager import StampStructureManager

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
        self.checked_elements: Set[tuple] = set()  # (page_num, element_type, index)
        self.cleaned_pdf_path: Optional[str] = None
        self.structure_loaded: bool = False
        self.current_preview_page: int = 0
        self.total_pages: int = 0
        self.selected_tree_item: Optional[QTreeWidgetItem] = None
        self.current_preview_pixmap: Optional[QPixmap] = None
        self.highlighted_element: Optional[PDFElement] = None
        
        self.setWindowTitle("Удаление электронных штампов")
        self.resize(1400, 900)
        
        logger.info("[StampRemover] Настройка UI...")
        try:
            self._setup_ui()
            
            # Инициализация менеджеров после создания UI
            self.preview_manager = StampPreviewManager(
                self, self.preview_label, self.page_spin, self.page_label,
                self.prev_page_btn, self.next_page_btn
            )
            self.structure_manager = StampStructureManager(
                self, self.structure_tree, self.stats_label,
                self.show_annotations_cb, self.show_images_cb, self.show_forms_cb
            )
            
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
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Основной сплиттер: слева структура, справа предпросмотр
        splitter = QSplitter(Qt.Horizontal)
        
        # Левая панель: структура
        left_panel = self._create_structure_panel()
        splitter.addWidget(left_panel)
        
        # Правая панель: предпросмотр с навигацией
        right_panel = self._create_preview_panel()
        splitter.addWidget(right_panel)
        
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        
        # Дерево элементов с чекбоксами
        self.structure_tree = QTreeWidget()
        self.structure_tree.setHeaderLabels(["Элемент", "Тип"])
        self.structure_tree.setColumnWidth(0, 250)
        self.structure_tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.structure_tree)
        
        # Кнопка "Выбрать такое на всех листах"
        self.select_similar_btn = QPushButton("✓ Выбрать такое на всех листах")
        self.select_similar_btn.clicked.connect(self._select_similar_on_all_pages)
        self.select_similar_btn.setEnabled(False)
        layout.addWidget(self.select_similar_btn)
        
        # Опции фильтрации
        filter_layout = QHBoxLayout()
        
        self.show_annotations_cb = QCheckBox("Аннотации")
        self.show_annotations_cb.setChecked(True)
        self.show_annotations_cb.stateChanged.connect(lambda: self.structure_manager.update_tree())
        filter_layout.addWidget(self.show_annotations_cb)
        
        self.show_images_cb = QCheckBox("Изображения")
        self.show_images_cb.setChecked(True)
        self.show_images_cb.stateChanged.connect(lambda: self.structure_manager.update_tree())
        filter_layout.addWidget(self.show_images_cb)
        
        self.show_forms_cb = QCheckBox("Контейнеры")
        self.show_forms_cb.setChecked(True)
        self.show_forms_cb.stateChanged.connect(lambda: self.structure_manager.update_tree())
        filter_layout.addWidget(self.show_forms_cb)
        
        layout.addLayout(filter_layout)
        
        # Статистика
        self.stats_label = QLabel("Всего элементов: 0 | Выбрано: 0")
        layout.addWidget(self.stats_label)
        
        return panel
    
    def _create_preview_panel(self):
        """Создать панель предпросмотра с навигацией"""
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
        
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        
        # Навигация по страницам
        nav_layout = QHBoxLayout()
        
        self.prev_page_btn = QPushButton("◀ Назад")
        self.prev_page_btn.clicked.connect(lambda: self.preview_manager.prev_page())
        nav_layout.addWidget(self.prev_page_btn)
        
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(lambda val: self.preview_manager.on_page_changed(val))
        nav_layout.addWidget(self.page_spin)
        
        self.page_label = QLabel("из 1")
        nav_layout.addWidget(self.page_label)
        
        self.next_page_btn = QPushButton("Вперед ▶")
        self.next_page_btn.clicked.connect(lambda: self.preview_manager.next_page())
        nav_layout.addWidget(self.next_page_btn)
        
        nav_layout.addStretch()
        
        layout.addLayout(nav_layout)
        
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
            self.total_pages = page_count
            logger.info(f"[StampRemover] Страниц в документе: {page_count}")
            
            # Обновляем навигацию
            self.page_spin.blockSignals(True)
            self.page_spin.setMaximum(max(1, page_count))
            self.page_spin.setValue(1)
            self.page_spin.blockSignals(False)
            self.page_label.setText(f"из {page_count}")
            
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
            self.structure_manager.update_tree()
            
            logger.info("[StampRemover] Отображение предпросмотра")
            self.current_preview_page = 0
            self.preview_manager.show_preview_page(0)
            self.preview_manager.update_navigation_buttons()
            
            logger.info("[StampRemover] Загрузка структуры завершена успешно")
        
        except Exception as e:
            logger.error(f"[StampRemover] Критическая ошибка загрузки структуры: {e}", exc_info=True)
            QMessageBox.critical(self, "Ошибка", f"Не удалось проанализировать PDF:\n{e}")
            self.reject()
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Обработка клика по элементу дерева"""
        data = item.data(0, Qt.UserRole)
        
        if data and data.get("type") == "element":
            elem = data["element"]
            elem_key = (elem.page_num, elem.element_type, elem.index)
            
            # Переключаем состояние чекбокса
            if item.checkState(0) == Qt.Checked:
                self.checked_elements.add(elem_key)
            else:
                self.checked_elements.discard(elem_key)
            
            # Запоминаем выбранный элемент для кнопки "Выбрать такое на всех листах"
            self.selected_tree_item = item
            self.select_similar_btn.setEnabled(True)
            
            # Подсвечиваем элемент в предпросмотре
            self.highlighted_element = elem
            if elem.page_num != self.current_preview_page:
                # Переключаемся на страницу элемента
                self.current_preview_page = elem.page_num
                self.page_spin.blockSignals(True)
                self.page_spin.setValue(elem.page_num + 1)
                self.page_spin.blockSignals(False)
                self.preview_manager.show_preview_page(elem.page_num)
                self.preview_manager.update_navigation_buttons()
            else:
                # Перерисовываем текущую страницу с подсветкой
                self.preview_manager.redraw_preview_with_highlight()
            
            self.stats_label.setText(f"Всего элементов: {self.structure_manager.count_total_elements()} | Выбрано: {len(self.checked_elements)}")
            
            logger.debug(f"Выбрано элементов: {len(self.checked_elements)}")
        
        elif data and data.get("type") == "page":
            # Клик по странице - переключаем все дочерние элементы
            page_num = data["page_num"]
            check_state = item.checkState(0)
            
            for i in range(item.childCount()):
                child = item.child(i)
                child.setCheckState(0, check_state)
                
                child_data = child.data(0, Qt.UserRole)
                if child_data and child_data.get("type") == "element":
                    elem = child_data["element"]
                    elem_key = (elem.page_num, elem.element_type, elem.index)
                    
                    if check_state == Qt.Checked:
                        self.checked_elements.add(elem_key)
                    else:
                        self.checked_elements.discard(elem_key)
            
            # Переключаемся на страницу
            if page_num != self.current_preview_page:
                self.current_preview_page = page_num
                self.page_spin.blockSignals(True)
                self.page_spin.setValue(page_num + 1)
                self.page_spin.blockSignals(False)
                self.preview_manager.show_preview_page(page_num)
                self.preview_manager.update_navigation_buttons()
            
            self.stats_label.setText(f"Всего элементов: {self.structure_manager.count_total_elements()} | Выбрано: {len(self.checked_elements)}")
    
    def _select_similar_on_all_pages(self):
        """Выбрать похожие элементы на всех страницах"""
        if not self.selected_tree_item:
            return
        
        data = self.selected_tree_item.data(0, Qt.UserRole)
        if not data or data.get("type") != "element":
            return
        
        selected_elem = data["element"]
        
        # Критерии поиска похожих элементов
        similar_count = 0
        for page_num, elements in self.page_elements.items():
            for elem in elements:
                if self.structure_manager.is_similar_element(selected_elem, elem):
                    elem_key = (elem.page_num, elem.element_type, elem.index)
                    self.checked_elements.add(elem_key)
                    similar_count += 1
        
        # Обновляем дерево
        self.structure_manager.update_tree()
        
        QMessageBox.information(
            self,
            "Выбрано",
            f"Выбрано {similar_count} похожих элементов на всех страницах"
        )
    
    def _remove_selected(self):
        """Удалить выбранные элементы"""
        if not self.checked_elements:
            QMessageBox.information(self, "Информация", "Выберите элементы для удаления")
            return
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить {len(self.checked_elements)} элемент(ов)?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Собираем элементы для удаления
        elements_to_remove = []
        for page_num, elements in self.page_elements.items():
            for elem in elements:
                elem_key = (elem.page_num, elem.element_type, elem.index)
                if elem_key in self.checked_elements:
                    elements_to_remove.append(elem)
        
        # Создаем временный файл с уникальным именем
        import time
        temp_dir = tempfile.gettempdir()
        timestamp = int(time.time() * 1000)
        original_name = Path(self.pdf_path).stem
        temp_pdf = Path(temp_dir) / f"cleaned_{original_name}_{timestamp}.pdf"
        
        logger.info(f"[StampRemover] Удаление элементов из: {self.pdf_path}")
        logger.info(f"[StampRemover] Сохранение очищенного PDF в: {temp_pdf}")
        
        # Удаляем элементы
        modifier = PDFStructureModifier(self.pdf_path)
        if modifier.open():
            count = modifier.remove_elements(elements_to_remove)
            
            if modifier.save(str(temp_pdf)):
                logger.info(f"[StampRemover] Очищенный PDF успешно сохранен")
                
                # Обновляем путь к PDF ПЕРЕД удалением элементов из структуры
                old_pdf_path = self.pdf_path
                self.pdf_path = str(temp_pdf)
                self.cleaned_pdf_path = str(temp_pdf)
                
                # Удаляем элементы из page_elements
                for elem_key in list(self.checked_elements):
                    page_num, elem_type, elem_index = elem_key
                    if page_num in self.page_elements:
                        # Находим и удаляем элемент
                        self.page_elements[page_num] = [
                            e for e in self.page_elements[page_num]
                            if not (e.element_type == elem_type and e.index == elem_index)
                        ]
                
                self.checked_elements.clear()
                self.highlighted_element = None
                
                logger.info(f"[StampRemover] Обновление дерева структуры")
                # Обновляем дерево
                self.structure_manager.update_tree()
                
                logger.info(f"[StampRemover] Перезагрузка предпросмотра страницы {self.current_preview_page}")
                # Перезагружаем предпросмотр из нового PDF
                self.preview_manager.show_preview_page(self.current_preview_page)
                
                QMessageBox.information(self, "Успех", f"Удалено {count} элемент(ов)")
            else:
                logger.error("[StampRemover] Не удалось сохранить очищенный PDF")
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
    

