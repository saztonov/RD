"""
Управление взаимодействием с блоками для PageViewer
"""

import logging
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QGraphicsRectItem
from PySide6.QtGui import QPen, QBrush, QColor
from app.models import Block, BlockType

logger = logging.getLogger(__name__)


class PageInteractionManager:
    """Управление взаимодействием пользователя с блоками"""
    
    def __init__(self, parent):
        self.parent = parent
    
    def handle_mouse_press(self, scene_pos: QPointF):
        """Обработка нажатия мыши"""
        x, y = scene_pos.x(), scene_pos.y()
        
        clicked_idx = self._find_block_at_pos(x, y)
        
        if clicked_idx is not None:
            if self.parent.selected_block_idx != clicked_idx:
                self.parent.selected_block_idx = clicked_idx
                self.parent.block_selected.emit(clicked_idx)
                self.parent.update_scene()
        else:
            if self.parent.draw_mode:
                self.parent.is_drawing = True
                self.parent.draw_start = (x, y)
                self.parent.current_rect_item = QGraphicsRectItem()
                pen = QPen(Qt.red, 2, Qt.DashLine)
                self.parent.current_rect_item.setPen(pen)
                brush = QBrush(QColor(255, 0, 0, 30))
                self.parent.current_rect_item.setBrush(brush)
                self.parent.scene().addItem(self.parent.current_rect_item)
    
    def handle_mouse_move(self, scene_pos: QPointF):
        """Обработка движения мыши"""
        if self.parent.is_drawing and self.parent.draw_start:
            x, y = scene_pos.x(), scene_pos.y()
            x0, y0 = self.parent.draw_start
            
            rect = QRectF(min(x0, x), min(y0, y), abs(x - x0), abs(y - y0))
            self.parent.current_rect_item.setRect(rect)
    
    def handle_mouse_release(self, scene_pos: QPointF):
        """Обработка отпускания мыши"""
        if self.parent.is_drawing and self.parent.draw_start:
            x, y = scene_pos.x(), scene_pos.y()
            x0, y0 = self.parent.draw_start
            
            x1, x2 = min(x0, x), max(x0, x)
            y1, y2 = min(y0, y), max(y0, y)
            
            if x2 - x1 > 5 and y2 - y1 > 5:
                new_block = Block(
                    coords_px=(int(x1), int(y1), int(x2), int(y2)),
                    block_type=BlockType.TEXT,
                    category=""
                )
                self.parent.block_drawn.emit(new_block)
            
            if self.parent.current_rect_item:
                self.parent.scene().removeItem(self.parent.current_rect_item)
                self.parent.current_rect_item = None
            
            self.parent.is_drawing = False
            self.parent.draw_start = None
    
    def handle_mouse_double_click(self, scene_pos: QPointF):
        """Обработка двойного клика"""
        x, y = scene_pos.x(), scene_pos.y()
        clicked_idx = self._find_block_at_pos(x, y)
        
        if clicked_idx is not None:
            self.parent.block_editing.emit(clicked_idx)
    
    def _find_block_at_pos(self, x: float, y: float):
        """Найти блок по позиции мыши"""
        for idx, block in enumerate(self.parent.current_page_blocks):
            x1, y1, x2, y2 = block.coords_px
            if x1 <= x <= x2 and y1 <= y <= y2:
                return idx
        return None

