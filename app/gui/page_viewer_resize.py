"""Миксин для resize handles в PageViewer"""

from PySide6.QtWidgets import QGraphicsRectItem
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QColor, QBrush
from typing import Optional, List


class ResizeHandlesMixin:
    """Методы для работы с хэндлами изменения размера"""
    
    def _draw_resize_handles(self, rect: QRectF):
        """Нарисовать хэндлы изменения размера на углах и сторонах прямоугольника"""
        handle_size = 8 / self.zoom_factor
        handle_color = QColor(255, 0, 0)
        
        positions = [
            (rect.left(), rect.top()),
            (rect.right(), rect.top()),
            (rect.left(), rect.bottom()),
            (rect.right(), rect.bottom()),
            (rect.center().x(), rect.top()),
            (rect.center().x(), rect.bottom()),
            (rect.left(), rect.center().y()),
            (rect.right(), rect.center().y()),
        ]
        
        for x, y in positions:
            handle_rect = QRectF(x - handle_size/2, y - handle_size/2, handle_size, handle_size)
            handle = QGraphicsRectItem(handle_rect)
            handle.setPen(QPen(handle_color, 1))
            handle.setBrush(QBrush(QColor(255, 255, 255)))
            self.scene.addItem(handle)
            self.resize_handles.append(handle)
    
    def _draw_polygon_handles(self, points: List[tuple]):
        """Нарисовать хэндлы на вершинах полигона"""
        handle_size = 8 / self.zoom_factor
        handle_color = QColor(255, 0, 0)
        
        for x, y in points:
            handle_rect = QRectF(x - handle_size/2, y - handle_size/2, handle_size, handle_size)
            handle = QGraphicsRectItem(handle_rect)
            handle.setPen(QPen(handle_color, 1))
            handle.setBrush(QBrush(QColor(255, 255, 255)))
            self.scene.addItem(handle)
            self.resize_handles.append(handle)
    
    def _clear_resize_handles(self):
        """Очистить все хэндлы изменения размера"""
        for handle in self.resize_handles:
            try:
                if handle.scene() is not None:
                    self.scene.removeItem(handle)
            except RuntimeError:
                pass
        self.resize_handles.clear()
    
    def _get_resize_handle(self, pos: QPointF, rect: QRectF) -> Optional[str]:
        """Определить, попал ли клик на хэндл изменения размера"""
        # Увеличиваем область клика для более удобного попадания
        handle_size = 15 / self.zoom_factor
        
        x, y = pos.x(), pos.y()
        left, top = rect.left(), rect.top()
        right, bottom = rect.right(), rect.bottom()
        
        # Проверяем углы (приоритет над сторонами)
        if abs(x - left) <= handle_size and abs(y - top) <= handle_size:
            return 'tl'
        if abs(x - right) <= handle_size and abs(y - top) <= handle_size:
            return 'tr'
        if abs(x - left) <= handle_size and abs(y - bottom) <= handle_size:
            return 'bl'
        if abs(x - right) <= handle_size and abs(y - bottom) <= handle_size:
            return 'br'
        
        # Проверяем стороны
        if abs(y - top) <= handle_size and left <= x <= right:
            return 't'
        if abs(y - bottom) <= handle_size and left <= x <= right:
            return 'b'
        if abs(x - left) <= handle_size and top <= y <= bottom:
            return 'l'
        if abs(x - right) <= handle_size and top <= y <= bottom:
            return 'r'
        
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
        block.coords_px = new_coords
        # Оптимизация: обновляем только один блок вместо перерисовки всех
        self._update_single_block_visual(block_idx)

