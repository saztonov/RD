"""
Виджет просмотра страницы PDF
Отображение страницы с возможностью рисовать прямоугольники для разметки
"""

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QMenu, QGraphicsTextItem
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QImage, QColor, QWheelEvent, QBrush, QAction, QFont
from PIL import Image
from typing import Optional, List, Dict
from app.models import Block, BlockType, BlockSource


class PageViewer(QGraphicsView):
    """
    Виджет для отображения страницы PDF и рисования блоков разметки
    Основан на QGraphicsView с поддержкой масштабирования колесом мыши
    
    Signals:
        blockDrawn: испускается при завершении рисования блока (x1, y1, x2, y2)
        block_selected: испускается при выборе существующего блока (int - индекс)
        blockEditing: испускается при двойном клике по блоку (int - индекс)
        blockDeleted: испускается при удалении блока (int - индекс)
        page_changed: испускается при запросе смены страницы (int - новая страница)
    """
    
    blockDrawn = Signal(int, int, int, int)  # x1, y1, x2, y2
    block_selected = Signal(int)
    blocks_selected = Signal(list)  # список индексов выбранных блоков
    blockEditing = Signal(int)  # индекс блока для редактирования
    blockDeleted = Signal(int)  # индекс блока, который удалили
    blocks_deleted = Signal(list)  # список индексов блоков для удаления
    blockMoved = Signal(int, int, int, int, int)  # индекс, x1, y1, x2, y2
    page_changed = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Scene для графики
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # Изображение страницы
        self.page_image: Optional[QPixmap] = None
        self.image_item: Optional[QGraphicsPixmapItem] = None
        self.current_blocks: List[Block] = []
        self.block_items: Dict[str, QGraphicsRectItem] = {}  # id блока -> QGraphicsRectItem
        self.block_labels: Dict[str, QGraphicsTextItem] = {}  # id блока -> QGraphicsTextItem
        self.resize_handles: List[QGraphicsRectItem] = []  # хэндлы изменения размера
        self.current_page: int = 0
        
        # Состояние рисования
        self.drawing = False
        self.selecting = False  # режим множественного выделения
        self.right_button_pressed = False  # ПКМ зажата
        self.start_point: Optional[QPointF] = None
        self.rubber_band_item: Optional[QGraphicsRectItem] = None  # временный прямоугольник
        self.selected_block_idx: Optional[int] = None
        self.selected_block_indices: List[int] = []  # список выбранных блоков
        
        # Состояние перемещения/изменения размера
        self.moving_block = False
        self.resizing_block = False
        self.resize_handle = None  # 'tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'
        self.move_start_pos: Optional[QPointF] = None
        self.original_block_rect: Optional[QRectF] = None
        
        # Масштабирование
        self.zoom_factor = 1.0
        
        # Настройка UI
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        # Настройки view
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumSize(800, 600)
        
        # Включаем отслеживание мыши и фокус
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Для запоминания позиции контекстного меню
        self.context_menu_pos: Optional[QPointF] = None
    
    def set_page_image(self, pil_image: Image.Image, page_number: int = 0, reset_zoom: bool = True):
        """
        Установить изображение страницы
        
        Args:
            pil_image: изображение страницы из PIL (может быть None для очистки)
            page_number: номер страницы
            reset_zoom: сбрасывать ли масштаб (по умолчанию True)
        """
        # Если изображение None - очищаем сцену
        if pil_image is None:
            self.scene.clear()
            self.page_image = None
            self.image_item = None
            self.current_page = page_number
            self.selected_block_idx = None
            self.block_items.clear()
            return
        
        # Конвертация PIL в QPixmap
        img_bytes = pil_image.tobytes("raw", "RGB")
        qimage = QImage(img_bytes, pil_image.width, pil_image.height, 
                       pil_image.width * 3, QImage.Format_RGB888)
        self.page_image = QPixmap.fromImage(qimage)
        self.current_page = page_number
        
        # Очищаем сцену и добавляем изображение
        self.scene.clear()
        self.image_item = self.scene.addPixmap(self.page_image)
        self.scene.setSceneRect(QRectF(self.page_image.rect()))
        
        # Сбрасываем выбранный блок при смене страницы
        self.selected_block_idx = None
        self.block_items.clear()
        self.block_labels.clear()
        
        # Сбрасываем масштаб только если указано
        if reset_zoom:
            self.resetTransform()
            self.zoom_factor = 1.0
    
    def set_blocks(self, blocks: List[Block]):
        """
        Установить список блоков для отображения
        
        Args:
            blocks: список блоков
        """
        self.current_blocks = blocks
        self._clear_block_items()
        self._draw_all_blocks()
    
    def _clear_block_items(self):
        """Очистить все QGraphicsRectItem блоков"""
        for item in self.block_items.values():
            self.scene.removeItem(item)
        self.block_items.clear()
        for label in self.block_labels.values():
            self.scene.removeItem(label)
        self.block_labels.clear()
        self._clear_resize_handles()
    
    def _clear_resize_handles(self):
        """Очистить все хэндлы изменения размера"""
        for handle in self.resize_handles:
            try:
                if handle.scene() is not None:
                    self.scene.removeItem(handle)
            except RuntimeError:
                pass
        self.resize_handles.clear()
    
    def _draw_all_blocks(self):
        """Отрисовать все блоки как QGraphicsRectItem"""
        for idx, block in enumerate(self.current_blocks):
            self._draw_block(block, idx)
    
    def _draw_block(self, block: Block, idx: int):
        """
        Отрисовать один блок как QGraphicsRectItem
        
        Args:
            block: блок для отрисовки
            idx: индекс блока в списке
        """
        x1, y1, x2, y2 = block.coords_px
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        
        # Создаём QGraphicsRectItem
        color = self._get_block_color(block.block_type)
        pen = QPen(color, 2)
        
        # Авто-блоки отображаем пунктирной линией
        if block.source == BlockSource.AUTO:
            pen.setStyle(Qt.DashLine)
            pen.setWidth(3)
        
        # Выделяем блок из множественного выделения синим цветом
        if idx in self.selected_block_indices:
            pen.setColor(QColor(0, 0, 255))  # синий
            pen.setWidth(4)
        
        # Выделяем выбранный блок
        if idx == self.selected_block_idx:
            pen.setWidth(4)
        
        # Полупрозрачная заливка
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), 30))
        
        rect_item = QGraphicsRectItem(rect)
        rect_item.setPen(pen)
        rect_item.setBrush(brush)
        
        # Сохраняем ссылку на блок в userData
        rect_item.setData(0, block.id)
        rect_item.setData(1, idx)
        
        self.scene.addItem(rect_item)
        self.block_items[block.id] = rect_item
        
        # Добавляем номер блока в правом верхнем углу
        label = QGraphicsTextItem(str(idx + 1))
        font = QFont("Arial", 12, QFont.Bold)
        label.setFont(font)
        label.setDefaultTextColor(QColor(255, 0, 0))  # Ярко-красный
        
        # Игнорируем трансформации view для постоянного размера
        label.setFlag(label.GraphicsItemFlag.ItemIgnoresTransformations, True)
        
        # Позиционируем в правом верхнем углу блока
        label.setPos(x2 - 20, y1 + 2)
        
        self.scene.addItem(label)
        self.block_labels[block.id] = label
        
        # Рисуем хэндлы для выделенного блока
        if idx == self.selected_block_idx:
            self._draw_resize_handles(rect)
    
    def _get_block_color(self, block_type: BlockType) -> QColor:
        """Получить цвет для типа блока"""
        colors = {
            BlockType.TEXT: QColor(0, 255, 0),    # зелёный
            BlockType.TABLE: QColor(0, 0, 255),   # синий
            BlockType.IMAGE: QColor(255, 140, 0), # оранжевый
        }
        return colors.get(block_type, QColor(128, 128, 128))
    
    def wheelEvent(self, event: QWheelEvent):
        """Обработка колеса мыши для масштабирования"""
        # Определяем направление прокрутки
        delta = event.angleDelta().y()
        
        if delta > 0:
            # Увеличение
            factor = 1.15
        else:
            # Уменьшение
            factor = 1 / 1.15
        
        # Применяем масштабирование
        self.zoom_factor *= factor
        self.scale(factor, factor)
        
        # Перерисовываем блоки для корректного отображения меток
        if self.current_blocks:
            self._redraw_blocks()
    
    def mousePressEvent(self, event):
        """Обработка нажатия мыши"""
        if event.button() == Qt.LeftButton:
            # Преобразуем координаты в координаты сцены
            scene_pos = self.mapToScene(event.pos())
            
            # Проверяем, попали ли в существующий блок
            clicked_block = self._find_block_at_position(scene_pos)
            
            # Режим Ctrl - добавление к выделению (как в AutoCAD)
            if event.modifiers() & Qt.ControlModifier:
                if clicked_block is not None:
                    # Добавляем/убираем блок из множественного выделения
                    if clicked_block in self.selected_block_indices:
                        self.selected_block_indices.remove(clicked_block)
                    else:
                        self.selected_block_indices.append(clicked_block)
                    
                    # Испускаем сигнал множественного выделения
                    if self.selected_block_indices:
                        self.blocks_selected.emit(self.selected_block_indices)
                    
                    self._redraw_blocks()
                return
            
            # Если не попали в блок, проверяем хэндл выбранного блока
            if clicked_block is None and self.selected_block_idx is not None:
                if 0 <= self.selected_block_idx < len(self.current_blocks):
                    block = self.current_blocks[self.selected_block_idx]
                    x1, y1, x2, y2 = block.coords_px
                    block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                    resize_handle = self._get_resize_handle(scene_pos, block_rect)
                    
                    if resize_handle:
                        # Начинаем изменение размера выбранного блока
                        self.parent().window()._save_undo_state()
                        self.resizing_block = True
                        self.resize_handle = resize_handle
                        self.move_start_pos = scene_pos
                        self.original_block_rect = block_rect
                        return
            
            if clicked_block is not None:
                self.selected_block_idx = clicked_block
                self.selected_block_indices = []  # очищаем множественное выделение
                self.block_selected.emit(clicked_block)
                
                # Определяем, куда кликнули: на хэндл изменения размера или в центр
                block = self.current_blocks[clicked_block]
                x1, y1, x2, y2 = block.coords_px
                block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                
                resize_handle = self._get_resize_handle(scene_pos, block_rect)
                
                if resize_handle:
                    # Начинаем изменение размера
                    self.parent().window()._save_undo_state()
                    self.resizing_block = True
                    self.resize_handle = resize_handle
                    self.move_start_pos = scene_pos
                    self.original_block_rect = block_rect
                else:
                    # Начинаем перемещение
                    self.parent().window()._save_undo_state()
                    self.moving_block = True
                    self.move_start_pos = scene_pos
                    self.original_block_rect = block_rect
                
                self._redraw_blocks()  # перерисовываем для выделения
            else:
                # Начинаем рисовать новый блок (rubber band)
                self.drawing = True
                self.start_point = scene_pos
                self.selected_block_indices = []  # очищаем множественное выделение
                
                # Создаём временный rubber band rect
                self.rubber_band_item = QGraphicsRectItem(QRectF(scene_pos, scene_pos))
                pen = QPen(QColor(255, 0, 0), 2, Qt.DashLine)
                brush = QBrush(QColor(255, 0, 0, 30))
                self.rubber_band_item.setPen(pen)
                self.rubber_band_item.setBrush(brush)
                self.scene.addItem(self.rubber_band_item)
        
        elif event.button() == Qt.RightButton:
            # Преобразуем координаты в координаты сцены
            scene_pos = self.mapToScene(event.pos())
            self.context_menu_pos = scene_pos
            self.right_button_pressed = True
            self.start_point = scene_pos
            
            # Проверяем, попали ли в существующий блок
            clicked_block = self._find_block_at_position(scene_pos)
            if clicked_block is not None:
                # Если кликнули на блок, который УЖЕ в множественном выделении - не сбрасываем
                if clicked_block not in self.selected_block_indices:
                    self.selected_block_idx = clicked_block
                    self.selected_block_indices = []  # очищаем множественное выделение
                    self.block_selected.emit(clicked_block)
                    self._redraw_blocks()
        
        elif event.button() == Qt.MiddleButton:
            # Средняя кнопка мыши для перетаскивания
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Обработка движения мыши - рисование rubber band, перемещение или изменение размера"""
        scene_pos = self.mapToScene(event.pos())
        
        # Проверяем начало рамки выбора через ПКМ
        if self.right_button_pressed and not self.selecting and self.start_point:
            # Если мышь сдвинулась на достаточное расстояние, начинаем рамку выбора
            distance = (scene_pos - self.start_point).manhattanLength()
            if distance > 5:
                self.selecting = True
                # Создаём временную рамку выбора
                self.rubber_band_item = QGraphicsRectItem(QRectF(self.start_point, scene_pos))
                pen = QPen(QColor(0, 120, 255), 2, Qt.DashLine)
                brush = QBrush(QColor(0, 120, 255, 30))
                self.rubber_band_item.setPen(pen)
                self.rubber_band_item.setBrush(brush)
                self.scene.addItem(self.rubber_band_item)
        
        if self.selecting and self.start_point and self.rubber_band_item:
            # Рамка выбора (множественное выделение)
            rect = QRectF(self.start_point, scene_pos).normalized()
            self.rubber_band_item.setRect(rect)
        
        elif self.drawing and self.start_point and self.rubber_band_item:
            # Рисование нового блока
            rect = QRectF(self.start_point, scene_pos).normalized()
            self.rubber_band_item.setRect(rect)
        
        elif self.moving_block and self.selected_block_idx is not None:
            # Перемещение блока
            delta = scene_pos - self.move_start_pos
            new_rect = self.original_block_rect.translated(delta)
            self._update_block_rect(self.selected_block_idx, new_rect)
        
        elif self.resizing_block and self.selected_block_idx is not None:
            # Изменение размера блока
            new_rect = self._calculate_resized_rect(scene_pos)
            self._update_block_rect(self.selected_block_idx, new_rect)
        
        else:
            # Обновляем курсор при наведении на хэндлы
            if self.selected_block_idx is not None and 0 <= self.selected_block_idx < len(self.current_blocks):
                block = self.current_blocks[self.selected_block_idx]
                x1, y1, x2, y2 = block.coords_px
                block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                resize_handle = self._get_resize_handle(scene_pos, block_rect)
                self._set_cursor_for_handle(resize_handle)
            else:
                self.setCursor(Qt.ArrowCursor)
            
            super().mouseMoveEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Обработка двойного клика - редактирование блока"""
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            clicked_block = self._find_block_at_position(scene_pos)
            
            if clicked_block is not None:
                self.blockEditing.emit(clicked_block)
    
    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши - финализация прямоугольника"""
        if event.button() == Qt.LeftButton:
            if self.drawing:
                self.drawing = False
                
                if self.rubber_band_item:
                    rect = self.rubber_band_item.rect()
                    
                    # Удаляем rubber band
                    self.scene.removeItem(self.rubber_band_item)
                    self.rubber_band_item = None
                    
                    # Проверяем минимальный размер
                    if rect.width() > 10 and rect.height() > 10:
                        # Посылаем сигнал с координатами
                        x1 = int(rect.x())
                        y1 = int(rect.y())
                        x2 = int(rect.x() + rect.width())
                        y2 = int(rect.y() + rect.height())
                        
                        self.blockDrawn.emit(x1, y1, x2, y2)
                
                self.start_point = None
            
            elif self.moving_block or self.resizing_block:
                # Завершение перемещения или изменения размера
                if self.selected_block_idx is not None and 0 <= self.selected_block_idx < len(self.current_blocks):
                    block = self.current_blocks[self.selected_block_idx]
                    x1, y1, x2, y2 = block.coords_px
                    self.blockMoved.emit(self.selected_block_idx, x1, y1, x2, y2)
                
                self.moving_block = False
                self.resizing_block = False
                self.resize_handle = None
                self.move_start_pos = None
                self.original_block_rect = None
        
        elif event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.NoDrag)
            super().mouseReleaseEvent(event)
        
        elif event.button() == Qt.RightButton:
            self.right_button_pressed = False
            
            if self.selecting:
                # Завершение режима множественного выделения (ПКМ)
                self.selecting = False
                
                if self.rubber_band_item:
                    rect = self.rubber_band_item.rect()
                    
                    # Удаляем рамку выбора
                    self.scene.removeItem(self.rubber_band_item)
                    self.rubber_band_item = None
                    
                    # Находим все блоки, попавшие в рамку
                    if rect.width() > 5 and rect.height() > 5:
                        selected_indices = self._find_blocks_in_rect(rect)
                        if selected_indices:
                            self.selected_block_indices = selected_indices
                            self.blocks_selected.emit(selected_indices)
                            self._redraw_blocks()
            else:
                # Показываем контекстное меню если не было рамки выбора
                if self.selected_block_idx is not None or self.selected_block_indices:
                    self._show_context_menu(event.globalPos())
            
            # Очищаем состояние
            self.start_point = None
    
    def keyPressEvent(self, event):
        """Обработка нажатия клавиш"""
        if event.key() == Qt.Key_Delete:
            # Если есть множественное выделение
            if self.selected_block_indices:
                self.blocks_deleted.emit(self.selected_block_indices)
                self.selected_block_indices = []
                self.selected_block_idx = None
            # Если выбран один блок
            elif self.selected_block_idx is not None:
                self.blockDeleted.emit(self.selected_block_idx)
                self.selected_block_idx = None
        elif event.key() == Qt.Key_Escape:
            # Сброс выделения
            self.selected_block_idx = None
            self.selected_block_indices = []
            self._redraw_blocks()
        else:
            super().keyPressEvent(event)
    
    def contextMenuEvent(self, event):
        """Обработка контекстного меню"""
        if self.selected_block_idx is not None:
            self._show_context_menu(event.globalPos())
    
    def _show_context_menu(self, global_pos):
        """Показать контекстное меню"""
        from app.models import BlockType
        
        menu = QMenu(self)
        
        # Определяем выбранные блоки
        selected_blocks = []
        if self.selected_block_indices:
            # Если есть множественное выделение
            for idx in self.selected_block_indices:
                selected_blocks.append({"idx": idx})
        elif self.selected_block_idx is not None:
            # Если выбран один блок
            selected_blocks.append({"idx": self.selected_block_idx})
        
        if not selected_blocks:
            return
        
        # Получаем главное окно для доступа к категориям
        main_window = self.parent().window()
        
        # Меню изменения типа
        type_menu = menu.addMenu(f"Изменить тип ({len(selected_blocks)} блоков)")
        for block_type in BlockType:
            action = type_menu.addAction(block_type.value)
            action.triggered.connect(lambda checked, bt=block_type, blocks=selected_blocks: 
                                    self._apply_type_to_blocks(blocks, bt))
        
        # Меню изменения категории
        cat_menu = menu.addMenu(f"Изменить категорию ({len(selected_blocks)} блоков)")
        for cat in sorted(main_window.categories):
            action = cat_menu.addAction(cat)
            action.triggered.connect(lambda checked, c=cat, blocks=selected_blocks: 
                                    self._apply_category_to_blocks(blocks, c))
        
        new_cat_action = cat_menu.addAction("Новая категория...")
        new_cat_action.triggered.connect(lambda blocks=selected_blocks: 
                                         self._apply_new_category_to_blocks(blocks))
        
        menu.addSeparator()
        
        # Только для одного блока
        if len(selected_blocks) == 1:
            edit_action = menu.addAction("Редактировать")
            edit_action.triggered.connect(lambda: self.blockEditing.emit(self.selected_block_idx))
        
        # Удаление
        delete_action = menu.addAction(f"Удалить ({len(selected_blocks)} блоков)")
        delete_action.triggered.connect(lambda blocks=selected_blocks: self._delete_blocks(blocks))
        
        menu.exec(global_pos)
    
    def _delete_selected_block(self):
        """Удалить выбранный блок"""
        if self.selected_block_idx is not None:
            self.blockDeleted.emit(self.selected_block_idx)
            self.selected_block_idx = None
    
    def _delete_blocks(self, blocks_data: list):
        """Удалить несколько блоков"""
        if len(blocks_data) == 1:
            self.blockDeleted.emit(blocks_data[0]["idx"])
        else:
            indices = [b["idx"] for b in blocks_data]
            self.blocks_deleted.emit(indices)
    
    def _apply_type_to_blocks(self, blocks_data: list, block_type):
        """Применить тип к нескольким блокам"""
        from app.models import BlockType
        
        main_window = self.parent().window()
        if not hasattr(main_window, 'annotation_document') or not main_window.annotation_document:
            return
        
        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return
        
        page = main_window.annotation_document.pages[current_page]
        
        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                page.blocks[block_idx].block_type = block_type
        
        # Обновляем отображение
        main_window._render_current_page()
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()
    
    def _apply_category_to_blocks(self, blocks_data: list, category: str):
        """Применить категорию к нескольким блокам"""
        main_window = self.parent().window()
        if not hasattr(main_window, 'annotation_document') or not main_window.annotation_document:
            return
        
        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return
        
        page = main_window.annotation_document.pages[current_page]
        
        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                page.blocks[block_idx].category = category
        
        # Обновляем отображение
        main_window._render_current_page()
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()
    
    def _apply_new_category_to_blocks(self, blocks_data: list):
        """Применить новую категорию к нескольким блокам"""
        from PySide6.QtWidgets import QInputDialog
        
        main_window = self.parent().window()
        text, ok = QInputDialog.getText(main_window, "Новая категория", "Введите название категории:")
        if not ok or not text.strip():
            return
        
        category = text.strip()
        
        # Добавляем категорию если новая
        if category and category not in main_window.categories:
            main_window.categories.append(category)
            if hasattr(main_window, 'category_manager'):
                main_window.category_manager.update_categories_list()
        
        # Применяем
        self._apply_category_to_blocks(blocks_data, category)
    
    def _find_block_at_position(self, scene_pos: QPointF) -> Optional[int]:
        """
        Найти блок в заданной позиции
        
        Returns:
            Индекс блока или None
        """
        # Используем itemAt для проверки QGraphicsRectItem
        item = self.scene.itemAt(scene_pos, self.transform())
        
        if isinstance(item, QGraphicsRectItem) and item != self.rubber_band_item:
            # Получаем индекс из userData
            idx = item.data(1)
            if idx is not None:
                return idx
        
        return None
    
    def _find_blocks_in_rect(self, rect: QRectF) -> List[int]:
        """
        Найти все блоки, попадающие в прямоугольник
        
        Returns:
            Список индексов блоков
        """
        selected_indices = []
        
        for idx, block in enumerate(self.current_blocks):
            x1, y1, x2, y2 = block.coords_px
            block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            
            # Проверяем пересечение или вхождение
            if rect.intersects(block_rect):
                selected_indices.append(idx)
        
        return selected_indices
    
    def _redraw_blocks(self):
        """Перерисовать все блоки (например, после смены выделения)"""
        self._clear_block_items()
        self._draw_all_blocks()
    
    def _get_resize_handle(self, pos: QPointF, rect: QRectF) -> Optional[str]:
        """
        Определить, попал ли клик на хэндл изменения размера
        
        Returns:
            'tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r' или None
        """
        handle_size = 10 / self.zoom_factor  # размер хэндла с учетом масштаба
        
        x, y = pos.x(), pos.y()
        left, top = rect.left(), rect.top()
        right, bottom = rect.right(), rect.bottom()
        
        # Проверяем углы (приоритет над сторонами)
        if abs(x - left) <= handle_size and abs(y - top) <= handle_size:
            return 'tl'  # top-left
        if abs(x - right) <= handle_size and abs(y - top) <= handle_size:
            return 'tr'  # top-right
        if abs(x - left) <= handle_size and abs(y - bottom) <= handle_size:
            return 'bl'  # bottom-left
        if abs(x - right) <= handle_size and abs(y - bottom) <= handle_size:
            return 'br'  # bottom-right
        
        # Проверяем стороны
        if abs(y - top) <= handle_size and left <= x <= right:
            return 't'  # top
        if abs(y - bottom) <= handle_size and left <= x <= right:
            return 'b'  # bottom
        if abs(x - left) <= handle_size and top <= y <= bottom:
            return 'l'  # left
        if abs(x - right) <= handle_size and top <= y <= bottom:
            return 'r'  # right
        
        return None
    
    def _set_cursor_for_handle(self, handle: Optional[str]):
        """Установить курсор в зависимости от хэндла"""
        if handle in ['tl', 'br']:
            self.setCursor(Qt.SizeFDiagCursor)
        elif handle in ['tr', 'bl']:
            self.setCursor(Qt.SizeBDiagCursor)
        elif handle in ['t', 'b']:
            self.setCursor(Qt.SizeVerCursor)
        elif handle in ['l', 'r']:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
    
    def _calculate_resized_rect(self, current_pos: QPointF) -> QRectF:
        """Вычислить новый прямоугольник при изменении размера"""
        if not self.original_block_rect or not self.move_start_pos:
            return self.original_block_rect
        
        delta = current_pos - self.move_start_pos
        rect = QRectF(self.original_block_rect)
        
        handle = self.resize_handle
        
        # Изменяем соответствующие стороны
        if 'l' in handle:
            rect.setLeft(rect.left() + delta.x())
        if 'r' in handle:
            rect.setRight(rect.right() + delta.x())
        if 't' in handle:
            rect.setTop(rect.top() + delta.y())
        if 'b' in handle:
            rect.setBottom(rect.bottom() + delta.y())
        
        # Минимальный размер
        if rect.width() < 10:
            if 'l' in handle:
                rect.setLeft(rect.right() - 10)
            else:
                rect.setRight(rect.left() + 10)
        
        if rect.height() < 10:
            if 't' in handle:
                rect.setTop(rect.bottom() - 10)
            else:
                rect.setBottom(rect.top() + 10)
        
        return rect.normalized()
    
    def _update_block_rect(self, block_idx: int, new_rect: QRectF):
        """Обновить координаты блока"""
        if block_idx >= len(self.current_blocks):
            return
        
        block = self.current_blocks[block_idx]
        new_coords = (
            int(new_rect.x()),
            int(new_rect.y()),
            int(new_rect.x() + new_rect.width()),
            int(new_rect.y() + new_rect.height())
        )
        
        # Обновляем координаты в блоке (временно, без пересчета нормализованных)
        block.coords_px = new_coords
        
        # Перерисовываем блок
        self._redraw_blocks()
    
    def reset_zoom(self):
        """Сбросить масштаб к 100%"""
        self.resetTransform()
        self.zoom_factor = 1.0
    
    def fit_to_view(self):
        """Подогнать страницу под размер view"""
        if self.page_image:
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            self.zoom_factor = self.transform().m11()
    
    def _draw_resize_handles(self, rect: QRectF):
        """Нарисовать хэндлы изменения размера на углах и сторонах прямоугольника"""
        handle_size = 8 / self.zoom_factor
        handle_color = QColor(255, 0, 0)
        
        positions = [
            (rect.left(), rect.top()),          # top-left
            (rect.right(), rect.top()),         # top-right
            (rect.left(), rect.bottom()),       # bottom-left
            (rect.right(), rect.bottom()),      # bottom-right
            (rect.center().x(), rect.top()),    # top-center
            (rect.center().x(), rect.bottom()), # bottom-center
            (rect.left(), rect.center().y()),   # left-center
            (rect.right(), rect.center().y()),  # right-center
        ]
        
        for x, y in positions:
            handle_rect = QRectF(x - handle_size/2, y - handle_size/2, 
                               handle_size, handle_size)
            handle = QGraphicsRectItem(handle_rect)
            handle.setPen(QPen(handle_color, 1))
            handle.setBrush(QBrush(QColor(255, 255, 255)))
            self.scene.addItem(handle)
            self.resize_handles.append(handle)

