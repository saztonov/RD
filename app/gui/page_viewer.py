"""
Виджет просмотра страницы PDF
Отображение страницы с возможностью рисовать прямоугольники для разметки
"""

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsPolygonItem, QMenu, QGraphicsTextItem, QGraphicsEllipseItem, QGraphicsLineItem
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QImage, QColor, QWheelEvent, QBrush, QFont, QPolygonF
from PIL import Image
from typing import Optional, List, Dict, Union
from rd_core.models import Block, BlockType, BlockSource, ShapeType

from app.gui.page_viewer_polygon import PolygonMixin
from app.gui.page_viewer_resize import ResizeHandlesMixin


class PageViewer(PolygonMixin, ResizeHandlesMixin, QGraphicsView):
    """
    Виджет для отображения страницы PDF и рисования блоков разметки
    """
    
    blockDrawn = Signal(int, int, int, int)
    polygonDrawn = Signal(list)
    block_selected = Signal(int)
    blocks_selected = Signal(list)
    blockEditing = Signal(int)
    blockDeleted = Signal(int)
    blocks_deleted = Signal(list)
    blockMoved = Signal(int, int, int, int, int)
    page_changed = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # Изображение страницы
        self.page_image: Optional[QPixmap] = None
        self.image_item: Optional[QGraphicsPixmapItem] = None
        self.current_blocks: List[Block] = []
        self.block_items: Dict[str, Union[QGraphicsRectItem, QGraphicsPolygonItem]] = {}
        self.block_labels: Dict[str, QGraphicsTextItem] = {}
        self.resize_handles: List[QGraphicsRectItem] = []
        self.current_page: int = 0
        
        # Состояние рисования
        self.drawing = False
        self.drawing_polygon = False
        self.polygon_points: List[QPointF] = []
        self.polygon_preview_items: List[QGraphicsEllipseItem] = []
        self.polygon_line_items: List[QGraphicsLineItem] = []
        self.polygon_temp_line: Optional[QGraphicsLineItem] = None
        self.selecting = False
        self.right_button_pressed = False
        self.start_point: Optional[QPointF] = None
        self.rubber_band_item: Optional[QGraphicsRectItem] = None
        self.selected_block_idx: Optional[int] = None
        self.selected_block_indices: List[int] = []
        
        # Состояние перемещения/изменения размера
        self.moving_block = False
        self.resizing_block = False
        self.resize_handle = None
        self.move_start_pos: Optional[QPointF] = None
        self.original_block_rect: Optional[QRectF] = None
        
        # Состояние редактирования полигона
        self.dragging_polygon_vertex: Optional[int] = None
        self.dragging_polygon_edge: Optional[int] = None
        self.original_polygon_points: Optional[List[tuple]] = None
        
        # Состояние панорамирования
        self.panning = False
        self.pan_start_pos: Optional[QPointF] = None
        
        self.zoom_factor = 1.0
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
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
        x1 = max(page_rect.left(), min(rect.left(), page_rect.right()))
        y1 = max(page_rect.top(), min(rect.top(), page_rect.bottom()))
        x2 = max(page_rect.left(), min(rect.right(), page_rect.right()))
        y2 = max(page_rect.top(), min(rect.bottom(), page_rect.bottom()))
        if x2 - x1 < 10:
            x2 = min(x1 + 10, page_rect.right())
        if y2 - y1 < 10:
            y2 = min(y1 + 10, page_rect.bottom())
        return QRectF(QPointF(x1, y1), QPointF(x2, y2))
    
    def set_page_image(self, pil_image: Image.Image, page_number: int = 0, reset_zoom: bool = True):
        """Установить изображение страницы"""
        if pil_image is None:
            self.scene.clear()
            self.page_image = None
            self.image_item = None
            self.current_page = page_number
            self.selected_block_idx = None
            self.block_items.clear()
            return
        
        img_bytes = pil_image.tobytes("raw", "RGB")
        qimage = QImage(img_bytes, pil_image.width, pil_image.height, 
                       pil_image.width * 3, QImage.Format_RGB888)
        self.page_image = QPixmap.fromImage(qimage)
        self.current_page = page_number
        
        self.scene.clear()
        self.image_item = self.scene.addPixmap(self.page_image)
        self.scene.setSceneRect(QRectF(self.page_image.rect()))
        
        self.selected_block_idx = None
        self.selected_block_indices = []
        self.block_items.clear()
        self.block_labels.clear()
        
        if reset_zoom:
            self.fit_to_view()
    
    def set_blocks(self, blocks: List[Block]):
        """Установить список блоков для отображения"""
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
    
    def _draw_all_blocks(self):
        """Отрисовать все блоки"""
        for idx, block in enumerate(self.current_blocks):
            self._draw_block(block, idx)
    
    def _draw_block(self, block: Block, idx: int):
        """Отрисовать один блок"""
        color = self._get_block_color(block.block_type)
        pen = QPen(color, 2)
        
        if block.source == BlockSource.AUTO:
            pen.setStyle(Qt.DashLine)
            pen.setWidth(3)
        
        if idx in self.selected_block_indices:
            pen.setColor(QColor(0, 0, 255))
            pen.setWidth(4)
        
        if idx == self.selected_block_idx:
            pen.setWidth(4)
        
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), 30))
        
        if block.shape_type == ShapeType.POLYGON and block.polygon_points:
            polygon = QPolygonF([QPointF(x, y) for x, y in block.polygon_points])
            poly_item = QGraphicsPolygonItem(polygon)
            poly_item.setPen(pen)
            poly_item.setBrush(brush)
            poly_item.setData(0, block.id)
            poly_item.setData(1, idx)
            self.scene.addItem(poly_item)
            self.block_items[block.id] = poly_item
            x1, y1, x2, y2 = block.coords_px
        else:
            x1, y1, x2, y2 = block.coords_px
            rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            rect_item = QGraphicsRectItem(rect)
            rect_item.setPen(pen)
            rect_item.setBrush(brush)
            rect_item.setData(0, block.id)
            rect_item.setData(1, idx)
            self.scene.addItem(rect_item)
            self.block_items[block.id] = rect_item
        
        x1, y1, x2, y2 = block.coords_px
        label = QGraphicsTextItem(str(idx + 1))
        font = QFont("Arial", 12, QFont.Bold)
        label.setFont(font)
        label.setDefaultTextColor(QColor(255, 0, 0))
        label.setFlag(label.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(x2 - 20, y1 + 2)
        self.scene.addItem(label)
        self.block_labels[block.id] = label
        
        if idx == self.selected_block_idx:
            if block.shape_type == ShapeType.RECTANGLE:
                rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                self._draw_resize_handles(rect)
            elif block.shape_type == ShapeType.POLYGON and block.polygon_points:
                self._draw_polygon_handles(block.polygon_points)
    
    def _get_block_color(self, block_type: BlockType) -> QColor:
        """Получить цвет для типа блока"""
        colors = {
            BlockType.TEXT: QColor(0, 255, 0),
            BlockType.TABLE: QColor(0, 0, 255),
            BlockType.IMAGE: QColor(255, 140, 0),
        }
        return colors.get(block_type, QColor(128, 128, 128))
    
    def wheelEvent(self, event: QWheelEvent):
        """Обработка колеса мыши для масштабирования"""
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.zoom_factor *= factor
        self.scale(factor, factor)
        if self.current_blocks:
            self._redraw_blocks()
    
    def mousePressEvent(self, event):
        """Обработка нажатия мыши"""
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            
            if self.drawing_polygon:
                self._add_polygon_point(scene_pos)
                return
            
            clicked_block = self._find_block_at_position(scene_pos)
            
            if event.modifiers() & Qt.ControlModifier:
                if clicked_block is not None:
                    if clicked_block in self.selected_block_indices:
                        self.selected_block_indices.remove(clicked_block)
                    else:
                        self.selected_block_indices.append(clicked_block)
                    if self.selected_block_indices:
                        self.blocks_selected.emit(self.selected_block_indices)
                    self._redraw_blocks()
                return
            
            if clicked_block is None and self.selected_block_idx is not None:
                if 0 <= self.selected_block_idx < len(self.current_blocks):
                    block = self.current_blocks[self.selected_block_idx]
                    x1, y1, x2, y2 = block.coords_px
                    block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                    
                    if block.shape_type == ShapeType.POLYGON and block.polygon_points:
                        vertex_idx = self._get_polygon_vertex_handle(scene_pos, block.polygon_points)
                        if vertex_idx is not None:
                            self.parent().window()._save_undo_state()
                            self.dragging_polygon_vertex = vertex_idx
                            self.move_start_pos = self._clamp_to_page(scene_pos)
                            self.original_polygon_points = list(block.polygon_points)
                            return
                        
                        edge_idx = self._get_polygon_edge_handle(scene_pos, block.polygon_points)
                        if edge_idx is not None:
                            self.parent().window()._save_undo_state()
                            self.dragging_polygon_edge = edge_idx
                            self.move_start_pos = self._clamp_to_page(scene_pos)
                            self.original_polygon_points = list(block.polygon_points)
                            return
                    
                    resize_handle = self._get_resize_handle(scene_pos, block_rect)
                    if resize_handle:
                        self.parent().window()._save_undo_state()
                        self.resizing_block = True
                        self.resize_handle = resize_handle
                        self.move_start_pos = self._clamp_to_page(scene_pos)
                        self.original_block_rect = block_rect
                        return
            
            if clicked_block is not None:
                self.selected_block_idx = clicked_block
                self.selected_block_indices = []
                self.block_selected.emit(clicked_block)
                
                block = self.current_blocks[clicked_block]
                x1, y1, x2, y2 = block.coords_px
                block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                
                if block.shape_type == ShapeType.POLYGON and block.polygon_points:
                    vertex_idx = self._get_polygon_vertex_handle(scene_pos, block.polygon_points)
                    if vertex_idx is not None:
                        self.parent().window()._save_undo_state()
                        self.dragging_polygon_vertex = vertex_idx
                        self.move_start_pos = self._clamp_to_page(scene_pos)
                        self.original_polygon_points = list(block.polygon_points)
                        self._redraw_blocks()
                        return
                    
                    edge_idx = self._get_polygon_edge_handle(scene_pos, block.polygon_points)
                    if edge_idx is not None:
                        self.parent().window()._save_undo_state()
                        self.dragging_polygon_edge = edge_idx
                        self.move_start_pos = self._clamp_to_page(scene_pos)
                        self.original_polygon_points = list(block.polygon_points)
                        self._redraw_blocks()
                        return
                
                resize_handle = self._get_resize_handle(scene_pos, block_rect)
                
                if resize_handle:
                    self.parent().window()._save_undo_state()
                    self.resizing_block = True
                    self.resize_handle = resize_handle
                    self.move_start_pos = self._clamp_to_page(scene_pos)
                    self.original_block_rect = block_rect
                else:
                    self.parent().window()._save_undo_state()
                    self.moving_block = True
                    self.move_start_pos = self._clamp_to_page(scene_pos)
                    self.original_block_rect = block_rect
                    if block.shape_type == ShapeType.POLYGON and block.polygon_points:
                        self.original_polygon_points = list(block.polygon_points)
                
                self._redraw_blocks()
            else:
                shape_type = self.get_current_shape_type()
                
                if shape_type == ShapeType.POLYGON:
                    self.drawing_polygon = True
                    self.polygon_points = []
                    self._add_polygon_point(scene_pos)
                else:
                    clamped_start = self._clamp_to_page(scene_pos)
                    self.drawing = True
                    self.start_point = clamped_start
                    self.selected_block_indices = []
                    
                    self.rubber_band_item = QGraphicsRectItem(QRectF(clamped_start, clamped_start))
                    pen = QPen(QColor(255, 0, 0), 2, Qt.DashLine)
                    brush = QBrush(QColor(255, 0, 0, 30))
                    self.rubber_band_item.setPen(pen)
                    self.rubber_band_item.setBrush(brush)
                    self.scene.addItem(self.rubber_band_item)
        
        elif event.button() == Qt.RightButton:
            scene_pos = self.mapToScene(event.pos())
            self.context_menu_pos = scene_pos
            self.right_button_pressed = True
            self.start_point = self._clamp_to_page(scene_pos)
            
            clicked_block = self._find_block_at_position(scene_pos)
            if clicked_block is not None:
                if clicked_block not in self.selected_block_indices:
                    self.selected_block_idx = clicked_block
                    self.selected_block_indices = []
                    self.block_selected.emit(clicked_block)
                    self._redraw_blocks()
        
        elif event.button() == Qt.MiddleButton:
            self.panning = True
            self.pan_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Обработка движения мыши"""
        if self.panning and self.pan_start_pos:
            delta = event.pos() - self.pan_start_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.pan_start_pos = event.pos()
            return
        
        scene_pos = self.mapToScene(event.pos())
        clamped_pos = self._clamp_to_page(scene_pos)
        
        if self.drawing_polygon and self.polygon_points:
            self._update_polygon_temp_line(clamped_pos)
            return
        
        if self.right_button_pressed and not self.selecting and self.start_point:
            distance = (scene_pos - self.start_point).manhattanLength()
            if distance > 5:
                self.selecting = True
                self.rubber_band_item = QGraphicsRectItem(QRectF(self.start_point, clamped_pos))
                pen = QPen(QColor(0, 120, 255), 2, Qt.DashLine)
                brush = QBrush(QColor(0, 120, 255, 30))
                self.rubber_band_item.setPen(pen)
                self.rubber_band_item.setBrush(brush)
                self.scene.addItem(self.rubber_band_item)
        
        if self.selecting and self.start_point and self.rubber_band_item:
            rect = QRectF(self.start_point, clamped_pos).normalized()
            self.rubber_band_item.setRect(rect)
        
        elif self.drawing and self.start_point and self.rubber_band_item:
            rect = QRectF(self.start_point, clamped_pos).normalized()
            self.rubber_band_item.setRect(rect)
        
        elif self.dragging_polygon_vertex is not None and self.selected_block_idx is not None:
            self._update_polygon_vertex(self.selected_block_idx, self.dragging_polygon_vertex, clamped_pos)
        
        elif self.dragging_polygon_edge is not None and self.selected_block_idx is not None:
            delta = clamped_pos - self.move_start_pos
            self._update_polygon_edge(self.selected_block_idx, self.dragging_polygon_edge, delta)
        
        elif self.moving_block and self.selected_block_idx is not None:
            delta = clamped_pos - self.move_start_pos
            block = self.current_blocks[self.selected_block_idx]
            
            if block.shape_type == ShapeType.POLYGON and self.original_polygon_points:
                self._move_polygon(self.selected_block_idx, delta)
            else:
                new_rect = self.original_block_rect.translated(delta)
                new_rect = self._clamp_rect_to_page(new_rect)
                self._update_block_rect(self.selected_block_idx, new_rect)
        
        elif self.resizing_block and self.selected_block_idx is not None:
            new_rect = self._calculate_resized_rect(clamped_pos)
            new_rect = self._clamp_rect_to_page(new_rect)
            self._update_block_rect(self.selected_block_idx, new_rect)
        
        else:
            if self.selected_block_idx is not None and 0 <= self.selected_block_idx < len(self.current_blocks):
                block = self.current_blocks[self.selected_block_idx]
                x1, y1, x2, y2 = block.coords_px
                block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                
                if block.shape_type == ShapeType.POLYGON and block.polygon_points:
                    vertex_idx = self._get_polygon_vertex_handle(scene_pos, block.polygon_points)
                    if vertex_idx is not None:
                        self.setCursor(Qt.SizeAllCursor)
                    else:
                        edge_idx = self._get_polygon_edge_handle(scene_pos, block.polygon_points)
                        if edge_idx is not None:
                            self.setCursor(Qt.SizeAllCursor)
                        else:
                            self.setCursor(Qt.ArrowCursor)
                else:
                    resize_handle = self._get_resize_handle(scene_pos, block_rect)
                    self._set_cursor_for_handle(resize_handle)
            else:
                self.setCursor(Qt.ArrowCursor)
            
            super().mouseMoveEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Обработка двойного клика"""
        if event.button() == Qt.LeftButton:
            if self.drawing_polygon:
                self._finish_polygon()
                return
            
            scene_pos = self.mapToScene(event.pos())
            clicked_block = self._find_block_at_position(scene_pos)
            
            if clicked_block is not None:
                self.blockEditing.emit(clicked_block)
    
    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши"""
        if event.button() == Qt.LeftButton:
            if self.drawing:
                self.drawing = False
                
                if self.rubber_band_item:
                    rect = self.rubber_band_item.rect()
                    rect = self._clamp_rect_to_page(rect)
                    self.scene.removeItem(self.rubber_band_item)
                    self.rubber_band_item = None
                    
                    if rect.width() > 10 and rect.height() > 10:
                        x1 = int(rect.x())
                        y1 = int(rect.y())
                        x2 = int(rect.x() + rect.width())
                        y2 = int(rect.y() + rect.height())
                        self.blockDrawn.emit(x1, y1, x2, y2)
                
                self.start_point = None
            
            elif self.moving_block or self.resizing_block or self.dragging_polygon_vertex is not None or self.dragging_polygon_edge is not None:
                if self.selected_block_idx is not None and 0 <= self.selected_block_idx < len(self.current_blocks):
                    block = self.current_blocks[self.selected_block_idx]
                    x1, y1, x2, y2 = block.coords_px
                    self.blockMoved.emit(self.selected_block_idx, x1, y1, x2, y2)
                
                self.moving_block = False
                self.resizing_block = False
                self.resize_handle = None
                self.move_start_pos = None
                self.original_block_rect = None
                self.dragging_polygon_vertex = None
                self.dragging_polygon_edge = None
                self.original_polygon_points = None
        
        elif event.button() == Qt.MiddleButton:
            self.panning = False
            self.pan_start_pos = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        
        elif event.button() == Qt.RightButton:
            self.right_button_pressed = False
            
            if self.selecting:
                self.selecting = False
                
                if self.rubber_band_item:
                    rect = self.rubber_band_item.rect()
                    self.scene.removeItem(self.rubber_band_item)
                    self.rubber_band_item = None
                    
                    if rect.width() > 5 and rect.height() > 5:
                        selected_indices = self._find_blocks_in_rect(rect)
                        if selected_indices:
                            self.selected_block_indices = selected_indices
                            self.blocks_selected.emit(selected_indices)
                            self._redraw_blocks()
            else:
                if self.selected_block_idx is not None or self.selected_block_indices:
                    self._show_context_menu(event.globalPos())
            
            self.start_point = None
    
    def keyPressEvent(self, event):
        """Обработка нажатия клавиш"""
        if event.key() == Qt.Key_Delete:
            if self.selected_block_indices:
                self.blocks_deleted.emit(self.selected_block_indices)
                self.selected_block_indices = []
                self.selected_block_idx = None
            elif self.selected_block_idx is not None:
                self.blockDeleted.emit(self.selected_block_idx)
                self.selected_block_idx = None
        elif event.key() == Qt.Key_Escape:
            if self.drawing_polygon:
                self._clear_polygon_preview()
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
        menu = QMenu(self)
        
        selected_blocks = []
        if self.selected_block_indices:
            for idx in self.selected_block_indices:
                selected_blocks.append({"idx": idx})
        elif self.selected_block_idx is not None:
            selected_blocks.append({"idx": self.selected_block_idx})
        
        if not selected_blocks:
            return
        
        type_menu = menu.addMenu(f"Изменить тип ({len(selected_blocks)} блоков)")
        for block_type in BlockType:
            action = type_menu.addAction(block_type.value)
            action.triggered.connect(lambda checked, bt=block_type, blocks=selected_blocks: 
                                    self._apply_type_to_blocks(blocks, bt))
        
        menu.addSeparator()
        
        if len(selected_blocks) == 1:
            edit_action = menu.addAction("Редактировать")
            edit_action.triggered.connect(lambda: self.blockEditing.emit(self.selected_block_idx))
        
        delete_action = menu.addAction(f"Удалить ({len(selected_blocks)} блоков)")
        delete_action.triggered.connect(lambda blocks=selected_blocks: self._delete_blocks(blocks))
        
        menu.exec(global_pos)
    
    def _delete_blocks(self, blocks_data: list):
        """Удалить несколько блоков"""
        if len(blocks_data) == 1:
            self.blockDeleted.emit(blocks_data[0]["idx"])
        else:
            indices = [b["idx"] for b in blocks_data]
            self.blocks_deleted.emit(indices)
    
    def _apply_type_to_blocks(self, blocks_data: list, block_type):
        """Применить тип к нескольким блокам"""
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
        
        main_window._render_current_page()
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()
    
    def _find_block_at_position(self, scene_pos: QPointF) -> Optional[int]:
        """Найти блок в заданной позиции"""
        item = self.scene.itemAt(scene_pos, self.transform())
        
        if item and item != self.rubber_band_item:
            if isinstance(item, QGraphicsRectItem):
                idx = item.data(1)
                if idx is not None:
                    return idx
            elif isinstance(item, QGraphicsPolygonItem):
                idx = item.data(1)
                if idx is not None:
                    return idx
        return None
    
    def _find_blocks_in_rect(self, rect: QRectF) -> List[int]:
        """Найти все блоки, попадающие в прямоугольник"""
        selected_indices = []
        for idx, block in enumerate(self.current_blocks):
            x1, y1, x2, y2 = block.coords_px
            block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            if rect.intersects(block_rect):
                selected_indices.append(idx)
        return selected_indices
    
    def _redraw_blocks(self):
        """Перерисовать все блоки"""
        self._clear_block_items()
        self._draw_all_blocks()
    
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
        if self.selected_block_indices:
            for idx in self.selected_block_indices:
                if 0 <= idx < len(self.current_blocks):
                    selected.append(self.current_blocks[idx])
        elif self.selected_block_idx is not None:
            if 0 <= self.selected_block_idx < len(self.current_blocks):
                selected.append(self.current_blocks[self.selected_block_idx])
        return selected
