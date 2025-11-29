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
        self.prev_page_btn.clicked.connect(self._prev_page)
        nav_layout.addWidget(self.prev_page_btn)
        
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._on_page_changed)
        nav_layout.addWidget(self.page_spin)
        
        self.page_label = QLabel("из 1")
        nav_layout.addWidget(self.page_label)
        
        self.next_page_btn = QPushButton("Вперед ▶")
        self.next_page_btn.clicked.connect(self._next_page)
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
            # Обновляем дерево
            self._update_tree()
            
            logger.info("[StampRemover] Отображение предпросмотра")
            # Показываем первую страницу
            self.current_preview_page = 0
            self._show_preview_page(0)
            self._update_navigation_buttons()
            
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
                page_item.setCheckState(0, Qt.Unchecked)
                page_item.setExpanded(True)
                
                # Добавляем элементы с чекбоксами
                for elem in filtered:
                    elem_item = QTreeWidgetItem(page_item)
                    elem_item.setText(0, elem.name)
                    elem_item.setText(1, elem.element_type.value)
                    elem_item.setData(0, Qt.UserRole, {"type": "element", "element": elem})
                    
                    # Устанавливаем чекбокс
                    elem_key = (elem.page_num, elem.element_type, elem.index)
                    if elem_key in self.checked_elements:
                        elem_item.setCheckState(0, Qt.Checked)
                    else:
                        elem_item.setCheckState(0, Qt.Unchecked)
                    
                    total_count += 1
            
            self.stats_label.setText(f"Всего элементов: {total_count} | Выбрано: {len(self.checked_elements)}")
            logger.debug(f"[StampRemover] _update_tree: завершено, элементов: {total_count}")
        
        except Exception as e:
            logger.error(f"[StampRemover] Ошибка обновления дерева: {e}", exc_info=True)
            self.stats_label.setText(f"Ошибка: {e}")
    
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
                self._show_preview_page(elem.page_num)
                self._update_navigation_buttons()
            else:
                # Перерисовываем текущую страницу с подсветкой
                self._redraw_preview_with_highlight()
            
            self.stats_label.setText(f"Всего элементов: {self._count_total_elements()} | Выбрано: {len(self.checked_elements)}")
            
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
                self._show_preview_page(page_num)
                self._update_navigation_buttons()
            
            self.stats_label.setText(f"Всего элементов: {self._count_total_elements()} | Выбрано: {len(self.checked_elements)}")
    
    def _count_total_elements(self) -> int:
        """Подсчитать общее количество элементов"""
        total = 0
        for elements in self.page_elements.values():
            total += len(elements)
        return total
    
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
                if self._is_similar_element(selected_elem, elem):
                    elem_key = (elem.page_num, elem.element_type, elem.index)
                    self.checked_elements.add(elem_key)
                    similar_count += 1
        
        # Обновляем дерево
        self._update_tree()
        
        QMessageBox.information(
            self,
            "Выбрано",
            f"Выбрано {similar_count} похожих элементов на всех страницах"
        )
    
    def _is_similar_element(self, elem1: PDFElement, elem2: PDFElement) -> bool:
        """Проверить, похожи ли два элемента"""
        # Одинаковый тип
        if elem1.element_type != elem2.element_type:
            return False
        
        # Для аннотаций: одинаковый подтип
        if elem1.element_type == PDFElementType.ANNOTATION:
            type1 = elem1.properties.get("type", "")
            type2 = elem2.properties.get("type", "")
            if type1 != type2:
                return False
        
        # Похожий размер (в пределах 10%)
        bbox1 = elem1.bbox
        bbox2 = elem2.bbox
        
        width1 = abs(bbox1[2] - bbox1[0])
        height1 = abs(bbox1[3] - bbox1[1])
        
        width2 = abs(bbox2[2] - bbox2[0])
        height2 = abs(bbox2[3] - bbox2[1])
        
        if width1 > 0 and height1 > 0 and width2 > 0 and height2 > 0:
            width_diff = abs(width1 - width2) / max(width1, width2)
            height_diff = abs(height1 - height2) / max(height1, height2)
            
            if width_diff > 0.1 or height_diff > 0.1:
                return False
        
        return True
    
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
                    self.current_preview_pixmap = pixmap  # Сохраняем оригинал
                    self.preview_label.setPixmap(scaled)
                    
                    # Если есть выделенный элемент на этой странице - подсвечиваем
                    if self.highlighted_element and self.highlighted_element.page_num == page_num:
                        self._redraw_preview_with_highlight()
                    
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
                self._update_tree()
                
                logger.info(f"[StampRemover] Перезагрузка предпросмотра страницы {self.current_preview_page}")
                # Перезагружаем предпросмотр из нового PDF
                self._show_preview_page(self.current_preview_page)
                
                QMessageBox.information(self, "Успех", f"Удалено {count} элемент(ов)")
            else:
                logger.error("[StampRemover] Не удалось сохранить очищенный PDF")
                QMessageBox.critical(self, "Ошибка", "Не удалось сохранить изменения")
            
            modifier.close()
    
    def _redraw_preview_with_highlight(self):
        """Перерисовать предпросмотр с подсветкой выделенного элемента"""
        if not self.current_preview_pixmap or not self.highlighted_element:
            return
        
        # Создаем копию pixmap для рисования
        pixmap = self.current_preview_pixmap.copy()
        
        # Рисуем bbox элемента
        painter = QPainter(pixmap)
        
        # Красный прямоугольник
        pen = QPen(QColor(255, 0, 0), 4)
        painter.setPen(pen)
        
        bbox = self.highlighted_element.bbox
        x0, y0, x1, y1 = bbox
        
        # Преобразуем координаты PDF в координаты изображения
        # PDF координаты обычно в точках, нужно масштабировать
        # Получаем размер отрендеренного изображения
        img_width = pixmap.width()
        img_height = pixmap.height()
        
        # Предполагаем, что bbox уже в координатах отрендеренного изображения
        # Если нет - нужно пересчитать через zoom factor
        # Для упрощения предполагаем zoom=1.5 (как в render_page)
        zoom = 1.5
        rect_x = int(x0 * zoom)
        rect_y = int(y0 * zoom)
        rect_w = int((x1 - x0) * zoom)
        rect_h = int((y1 - y0) * zoom)
        
        painter.drawRect(rect_x, rect_y, rect_w, rect_h)
        painter.end()
        
        # Масштабируем и отображаем
        scaled = pixmap.scaled(800, 1000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)
    
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
    
    def _prev_page(self):
        """Перейти на предыдущую страницу"""
        if self.current_preview_page > 0:
            self.current_preview_page -= 1
            self.page_spin.blockSignals(True)
            self.page_spin.setValue(self.current_preview_page + 1)
            self.page_spin.blockSignals(False)
            # Очищаем подсветку если элемент не на текущей странице
            if self.highlighted_element and self.highlighted_element.page_num != self.current_preview_page:
                self.highlighted_element = None
            self._show_preview_page(self.current_preview_page)
            self._update_navigation_buttons()
    
    def _next_page(self):
        """Перейти на следующую страницу"""
        if self.current_preview_page < self.total_pages - 1:
            self.current_preview_page += 1
            self.page_spin.blockSignals(True)
            self.page_spin.setValue(self.current_preview_page + 1)
            self.page_spin.blockSignals(False)
            # Очищаем подсветку если элемент не на текущей странице
            if self.highlighted_element and self.highlighted_element.page_num != self.current_preview_page:
                self.highlighted_element = None
            self._show_preview_page(self.current_preview_page)
            self._update_navigation_buttons()
    
    def _on_page_changed(self, value: int):
        """Обработка изменения номера страницы"""
        new_page = value - 1  # SpinBox показывает 1-based, внутри храним 0-based
        if 0 <= new_page < self.total_pages:
            if new_page != self.current_preview_page:
                self.current_preview_page = new_page
                # Очищаем подсветку если элемент не на текущей странице
                if self.highlighted_element and self.highlighted_element.page_num != self.current_preview_page:
                    self.highlighted_element = None
                self._show_preview_page(self.current_preview_page)
            self._update_navigation_buttons()
    
    def _update_navigation_buttons(self):
        """Обновить состояние кнопок навигации"""
        self.prev_page_btn.setEnabled(self.current_preview_page > 0)
        self.next_page_btn.setEnabled(self.current_preview_page < self.total_pages - 1)

