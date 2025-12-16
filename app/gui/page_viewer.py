"""
Виджет просмотра страницы PDF
Отображение страницы с возможностью рисовать прямоугольники для разметки
"""

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsPolygonItem, QMenu, QGraphicsTextItem, QGraphicsEllipseItem, QGraphicsLineItem
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QImage, QColor, QWheelEvent, QBrush, QAction, QFont, QPolygonF
from PIL import Image
from typing import Optional, List, Dict, Union
from rd_core.models import Block, BlockType, BlockSource, ShapeType


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
    
    blockDrawn = Signal(int, int, int, int)  # x1, y1, x2, y2 (для прямоугольников)
    polygonDrawn = Signal(list)  # [(x1, y1), (x2, y2), ...] (для полигонов)
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
        self.block_items: Dict[str, Union[QGraphicsRectItem, QGraphicsPolygonItem]] = {}  # id блока -> item
        self.block_labels: Dict[str, QGraphicsTextItem] = {}  # id блока -> QGraphicsTextItem
        self.resize_handles: List[QGraphicsRectItem] = []  # хэндлы изменения размера
        self.current_page: int = 0
        
        # Состояние рисования
        self.drawing = False
        self.drawing_polygon = False  # режим рисования полигона
        self.polygon_points: List[QPointF] = []  # точки полигона
        self.polygon_preview_items: List[QGraphicsEllipseItem] = []  # маркеры точек
        self.polygon_line_items: List[QGraphicsLineItem] = []  # линии между точками
        self.polygon_temp_line: Optional[QGraphicsLineItem] = None  # временная линия от последней точки к курсору
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
        
        # Состояние панорамирования (перемещения листа)
        self.panning = False
        self.pan_start_pos: Optional[QPointF] = None
        
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
    
    def get_current_shape_type(self) -> ShapeType:
        """Получить текущий выбранный тип формы из главного окна"""
        main_window = self.parent().window()
        if hasattr(main_window, 'selected_shape_type'):
            return main_window.selected_shape_type
        return ShapeType.RECTANGLE
    
    def _clamp_to_page(self, point: QPointF) -> QPointF:
        """Ограничить точку границами страницы"""
        if not self.page_image:
            return point
        
        page_rect = self.scene.sceneRect()
        x = max(page_rect.left(), min(point.x(), page_rect.right()))
        y = max(page_rect.top(), min(point.y(), page_rect.bottom()))
        return QPointF(x, y)
    
    def _clamp_rect_to_page(self, rect: QRectF) -> QRectF:
        """Ограничить прямоугольник границами страницы"""
        if not self.page_image:
            return rect
        
        page_rect = self.scene.sceneRect()
        
        # Ограничиваем координаты
        x1 = max(page_rect.left(), min(rect.left(), page_rect.right()))
        y1 = max(page_rect.top(), min(rect.top(), page_rect.bottom()))
        x2 = max(page_rect.left(), min(rect.right(), page_rect.right()))
        y2 = max(page_rect.top(), min(rect.bottom(), page_rect.bottom()))
        
        # Проверяем минимальный размер
        if x2 - x1 < 10:
            x2 = min(x1 + 10, page_rect.right())
        if y2 - y1 < 10:
            y2 = min(y1 + 10, page_rect.bottom())
        
        return QRectF(QPointF(x1, y1), QPointF(x2, y2))
    
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
        self.selected_block_indices = []  # Сброс множественного выделения
        self.block_items.clear()
        self.block_labels.clear()
        
        # Вписываем страницу в область просмотра только если указано
        if reset_zoom:
            self.fit_to_view()
    
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
        Отрисовать один блок (прямоугольник или полигон)
        
        Args:
            block: блок для отрисовки
            idx: индекс блока в списке
        """
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
        
        # Рисуем в зависимости от типа формы
        if block.shape_type == ShapeType.POLYGON and block.polygon_points:
            # Рисуем полигон
            polygon = QPolygonF([QPointF(x, y) for x, y in block.polygon_points])
            poly_item = QGraphicsPolygonItem(polygon)
            poly_item.setPen(pen)
            poly_item.setBrush(brush)
            poly_item.setData(0, block.id)
            poly_item.setData(1, idx)
            self.scene.addItem(poly_item)
            self.block_items[block.id] = poly_item
            
            # Координаты для метки - используем bounding box
            x1, y1, x2, y2 = block.coords_px
        else:
            # Рисуем прямоугольник
            x1, y1, x2, y2 = block.coords_px
            rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            rect_item = QGraphicsRectItem(rect)
            rect_item.setPen(pen)
            rect_item.setBrush(brush)
            rect_item.setData(0, block.id)
            rect_item.setData(1, idx)
            self.scene.addItem(rect_item)
            self.block_items[block.id] = rect_item
        
        # Добавляем номер блока в правом верхнем углу
        x1, y1, x2, y2 = block.coords_px
        label = QGraphicsTextItem(str(idx + 1))
        font = QFont("Arial", 12, QFont.Bold)
        label.setFont(font)
        label.setDefaultTextColor(QColor(255, 0, 0))  # Ярко-красный
        label.setFlag(label.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(x2 - 20, y1 + 2)
        self.scene.addItem(label)
        self.block_labels[block.id] = label
        
        # Рисуем хэндлы для выделенного блока (только для прямоугольников)
        if idx == self.selected_block_idx and block.shape_type == ShapeType.RECTANGLE:
            rect = QRectF(x1, y1, x2 - x1, y2 - y1)
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
            
            # Если идет рисование полигона - добавляем точку
            if self.drawing_polygon:
                self._add_polygon_point(scene_pos)
                return
            
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
                        self.move_start_pos = self._clamp_to_page(scene_pos)
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
                    self.move_start_pos = self._clamp_to_page(scene_pos)
                    self.original_block_rect = block_rect
                else:
                    # Начинаем перемещение
                    self.parent().window()._save_undo_state()
                    self.moving_block = True
                    self.move_start_pos = self._clamp_to_page(scene_pos)
                    self.original_block_rect = block_rect
                
                self._redraw_blocks()  # перерисовываем для выделения
            else:
                # Начинаем рисовать новый блок
                shape_type = self.get_current_shape_type()
                
                if shape_type == ShapeType.POLYGON:
                    # Начинаем рисовать полигон
                    self.drawing_polygon = True
                    self.polygon_points = []
                    self._add_polygon_point(scene_pos)
                else:
                    # Начинаем рисовать прямоугольник (rubber band)
                    clamped_start = self._clamp_to_page(scene_pos)
                    self.drawing = True
                    self.start_point = clamped_start
                    self.selected_block_indices = []  # очищаем множественное выделение
                    
                    # Создаём временный rubber band rect
                    self.rubber_band_item = QGraphicsRectItem(QRectF(clamped_start, clamped_start))
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
            self.start_point = self._clamp_to_page(scene_pos)
            
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
            self.panning = True
            self.pan_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Обработка движения мыши - рисование rubber band, перемещение или изменение размера"""
        # Обработка панорамирования (перемещения листа средней кнопкой)
        if self.panning and self.pan_start_pos:
            delta = event.pos() - self.pan_start_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.pan_start_pos = event.pos()
            return
        
        scene_pos = self.mapToScene(event.pos())
        clamped_pos = self._clamp_to_page(scene_pos)
        
        # Обновление временной линии при рисовании полигона
        if self.drawing_polygon and self.polygon_points:
            self._update_polygon_temp_line(clamped_pos)
            return
        
        # Проверяем начало рамки выбора через ПКМ
        if self.right_button_pressed and not self.selecting and self.start_point:
            # Если мышь сдвинулась на достаточное расстояние, начинаем рамку выбора
            distance = (scene_pos - self.start_point).manhattanLength()
            if distance > 5:
                self.selecting = True
                # Создаём временную рамку выбора
                self.rubber_band_item = QGraphicsRectItem(QRectF(self.start_point, clamped_pos))
                pen = QPen(QColor(0, 120, 255), 2, Qt.DashLine)
                brush = QBrush(QColor(0, 120, 255, 30))
                self.rubber_band_item.setPen(pen)
                self.rubber_band_item.setBrush(brush)
                self.scene.addItem(self.rubber_band_item)
        
        if self.selecting and self.start_point and self.rubber_band_item:
            # Рамка выбора (множественное выделение)
            rect = QRectF(self.start_point, clamped_pos).normalized()
            self.rubber_band_item.setRect(rect)
        
        elif self.drawing and self.start_point and self.rubber_band_item:
            # Рисование нового блока
            rect = QRectF(self.start_point, clamped_pos).normalized()
            self.rubber_band_item.setRect(rect)
        
        elif self.moving_block and self.selected_block_idx is not None:
            # Перемещение блока
            delta = clamped_pos - self.move_start_pos
            new_rect = self.original_block_rect.translated(delta)
            new_rect = self._clamp_rect_to_page(new_rect)
            self._update_block_rect(self.selected_block_idx, new_rect)
        
        elif self.resizing_block and self.selected_block_idx is not None:
            # Изменение размера блока
            new_rect = self._calculate_resized_rect(clamped_pos)
            new_rect = self._clamp_rect_to_page(new_rect)
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
        """Обработка двойного клика - редактирование блока или завершение полигона"""
        if event.button() == Qt.LeftButton:
            # Если идет рисование полигона - завершаем его
            if self.drawing_polygon:
                self._finish_polygon()
                return
            
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
                    rect = self._clamp_rect_to_page(rect)
                    
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
            self.panning = False
            self.pan_start_pos = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        
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
            # Отмена рисования полигона
            if self.drawing_polygon:
                self._clear_polygon_preview()
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
        from rd_core.models import BlockType
        
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
        
        # Меню изменения типа
        type_menu = menu.addMenu(f"Изменить тип ({len(selected_blocks)} блоков)")
        for block_type in BlockType:
            action = type_menu.addAction(block_type.value)
            action.triggered.connect(lambda checked, bt=block_type, blocks=selected_blocks: 
                                    self._apply_type_to_blocks(blocks, bt))
        
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
        from rd_core.models import BlockType
        
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
    
    def _find_block_at_position(self, scene_pos: QPointF) -> Optional[int]:
        """
        Найти блок в заданной позиции
        
        Returns:
            Индекс блока или None
        """
        # Используем itemAt для проверки графических элементов
        item = self.scene.itemAt(scene_pos, self.transform())
        
        if item and item != self.rubber_band_item:
            # Проверяем прямоугольники
            if isinstance(item, QGraphicsRectItem):
                idx = item.data(1)
                if idx is not None:
                    return idx
            # Проверяем полигоны
            elif isinstance(item, QGraphicsPolygonItem):
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
    
    def get_selected_blocks(self) -> List[Block]:
        """Получить список выбранных блоков"""
        selected = []
        
        # Множественное выделение
        if self.selected_block_indices:
            for idx in self.selected_block_indices:
                if 0 <= idx < len(self.current_blocks):
                    selected.append(self.current_blocks[idx])
        # Одиночное выделение
        elif self.selected_block_idx is not None:
            if 0 <= self.selected_block_idx < len(self.current_blocks):
                selected.append(self.current_blocks[self.selected_block_idx])
        
        return selected
    
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
    
    def _add_polygon_point(self, point: QPointF):
        """Добавить точку в полигон"""
        clamped_point = self._clamp_to_page(point)
        self.polygon_points.append(clamped_point)
        
        # Рисуем маркер точки
        marker_size = 6 / self.zoom_factor
        marker = QGraphicsEllipseItem(
            clamped_point.x() - marker_size/2, 
            clamped_point.y() - marker_size/2,
            marker_size, 
            marker_size
        )
        marker.setPen(QPen(QColor(255, 0, 0), 2))
        marker.setBrush(QBrush(QColor(255, 0, 0)))
        self.scene.addItem(marker)
        self.polygon_preview_items.append(marker)
        
        # Рисуем линию от предыдущей точки
        if len(self.polygon_points) > 1:
            prev_point = self.polygon_points[-2]
            line = QGraphicsLineItem(prev_point.x(), prev_point.y(), clamped_point.x(), clamped_point.y())
            line.setPen(QPen(QColor(255, 0, 0), 2))
            self.scene.addItem(line)
            self.polygon_line_items.append(line)
    
    def _update_polygon_temp_line(self, current_pos: QPointF):
        """Обновить временную линию от последней точки к курсору"""
        if not self.polygon_points:
            return
        
        # Удаляем старую временную линию
        if self.polygon_temp_line:
            try:
                self.scene.removeItem(self.polygon_temp_line)
            except RuntimeError:
                # C++ объект уже удалён
                pass
            self.polygon_temp_line = None
        
        # Создаём новую временную линию
        last_point = self.polygon_points[-1]
        self.polygon_temp_line = QGraphicsLineItem(
            last_point.x(), last_point.y(),
            current_pos.x(), current_pos.y()
        )
        self.polygon_temp_line.setPen(QPen(QColor(255, 0, 0, 128), 1, Qt.DashLine))
        self.scene.addItem(self.polygon_temp_line)
    
    def _finish_polygon(self):
        """Завершить рисование полигона и создать блок"""
        if len(self.polygon_points) < 3:
            # Нужно минимум 3 точки для полигона
            self._clear_polygon_preview()
            return
        
        # Конвертируем точки в координаты
        points = [(int(p.x()), int(p.y())) for p in self.polygon_points]
        
        # Испускаем сигнал с точками полигона
        self.polygonDrawn.emit(points)
        
        # Очищаем превью
        self._clear_polygon_preview()
    
    def _clear_polygon_preview(self):
        """Очистить превью полигона (маркеры и линии)"""
        # Удаляем маркеры
        for marker in self.polygon_preview_items:
            try:
                if marker.scene() is not None:
                    self.scene.removeItem(marker)
            except RuntimeError:
                pass
        self.polygon_preview_items.clear()
        
        # Удаляем линии
        for line in self.polygon_line_items:
            try:
                if line.scene() is not None:
                    self.scene.removeItem(line)
            except RuntimeError:
                pass
        self.polygon_line_items.clear()
        
        # Удаляем временную линию
        if self.polygon_temp_line:
            try:
                if self.polygon_temp_line.scene() is not None:
                    self.scene.removeItem(self.polygon_temp_line)
            except RuntimeError:
                pass
            self.polygon_temp_line = None
        
        # Сбрасываем состояние
        self.drawing_polygon = False
        self.polygon_points.clear()

