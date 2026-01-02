"""Миксин для работы с полигонами в PageViewer"""

from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsLineItem
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPen, QColor, QBrush
from typing import Optional, List


class PolygonMixin:
    """Методы для рисования и редактирования полигонов"""
    
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
            self._clear_polygon_preview()
            return
        
        points = [(int(p.x()), int(p.y())) for p in self.polygon_points]
        self.polygonDrawn.emit(points)
        self._clear_polygon_preview()
    
    def _clear_polygon_preview(self):
        """Очистить превью полигона (маркеры и линии)"""
        for marker in self.polygon_preview_items:
            try:
                if marker.scene() is not None:
                    self.scene.removeItem(marker)
            except RuntimeError:
                pass
        self.polygon_preview_items.clear()
        
        for line in self.polygon_line_items:
            try:
                if line.scene() is not None:
                    self.scene.removeItem(line)
            except RuntimeError:
                pass
        self.polygon_line_items.clear()
        
        if self.polygon_temp_line:
            try:
                if self.polygon_temp_line.scene() is not None:
                    self.scene.removeItem(self.polygon_temp_line)
            except RuntimeError:
                pass
            self.polygon_temp_line = None
        
        self.drawing_polygon = False
        self.polygon_points.clear()
    
    def _get_polygon_vertex_handle(self, pos: QPointF, points: List[tuple]) -> Optional[int]:
        """Определить, попал ли клик на вершину полигона"""
        # Увеличиваем область клика для более удобного попадания
        handle_size = 15 / self.zoom_factor
        
        for idx, (px, py) in enumerate(points):
            if abs(pos.x() - px) <= handle_size and abs(pos.y() - py) <= handle_size:
                return idx
        return None
    
    def _get_polygon_edge_handle(self, pos: QPointF, points: List[tuple]) -> Optional[int]:
        """Определить, попал ли клик на ребро полигона"""
        # Увеличиваем область клика для более удобного попадания
        edge_threshold = 12 / self.zoom_factor
        
        for i in range(len(points)):
            p1 = points[i]
            p2 = points[(i + 1) % len(points)]
            dist = self._point_to_segment_distance(pos, p1, p2)
            if dist <= edge_threshold:
                return i
        return None
    
    def _point_to_segment_distance(self, point: QPointF, p1: tuple, p2: tuple) -> float:
        """Расстояние от точки до отрезка"""
        px, py = point.x(), point.y()
        x1, y1 = p1
        x2, y2 = p2
        
        dx = x2 - x1
        dy = y2 - y1
        
        if dx == 0 and dy == 0:
            return ((px - x1)**2 + (py - y1)**2)**0.5
        
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        
        return ((px - proj_x)**2 + (py - proj_y)**2)**0.5
    
    def _update_polygon_vertex(self, block_idx: int, vertex_idx: int, new_pos: QPointF):
        """Обновить позицию вершины полигона"""
        if block_idx >= len(self.current_blocks):
            return
        
        block = self.current_blocks[block_idx]
        if not block.polygon_points or vertex_idx >= len(block.polygon_points):
            return
        
        new_points = list(block.polygon_points)
        new_points[vertex_idx] = (int(new_pos.x()), int(new_pos.y()))
        block.polygon_points = new_points
        
        xs = [p[0] for p in new_points]
        ys = [p[1] for p in new_points]
        block.coords_px = (min(xs), min(ys), max(xs), max(ys))
        
        # Оптимизация: обновляем только один блок
        self._update_single_block_visual(block_idx)
    
    def _move_polygon(self, block_idx: int, delta: QPointF):
        """Переместить весь полигон"""
        if block_idx >= len(self.current_blocks):
            return
        
        block = self.current_blocks[block_idx]
        if not self.original_polygon_points:
            return
        
        new_points = []
        for px, py in self.original_polygon_points:
            new_x = int(px + delta.x())
            new_y = int(py + delta.y())
            new_pos = self._clamp_to_page(QPointF(new_x, new_y))
            new_points.append((int(new_pos.x()), int(new_pos.y())))
        
        block.polygon_points = new_points
        
        xs = [p[0] for p in new_points]
        ys = [p[1] for p in new_points]
        block.coords_px = (min(xs), min(ys), max(xs), max(ys))
        
        # Оптимизация: обновляем только один блок
        self._update_single_block_visual(block_idx)
    
    def _update_polygon_edge(self, block_idx: int, edge_idx: int, delta: QPointF):
        """Переместить ребро полигона (две смежные вершины)"""
        if block_idx >= len(self.current_blocks):
            return
        
        block = self.current_blocks[block_idx]
        if not self.original_polygon_points:
            return
        
        n = len(self.original_polygon_points)
        i1 = edge_idx
        i2 = (edge_idx + 1) % n
        
        new_points = list(self.original_polygon_points)
        
        for idx in [i1, i2]:
            px, py = self.original_polygon_points[idx]
            new_x = int(px + delta.x())
            new_y = int(py + delta.y())
            new_pos = self._clamp_to_page(QPointF(new_x, new_y))
            new_points[idx] = (int(new_pos.x()), int(new_pos.y()))
        
        block.polygon_points = new_points
        
        xs = [p[0] for p in new_points]
        ys = [p[1] for p in new_points]
        block.coords_px = (min(xs), min(ys), max(xs), max(ys))
        
        # Оптимизация: обновляем только один блок
        self._update_single_block_visual(block_idx)

