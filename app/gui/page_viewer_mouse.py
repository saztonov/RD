"""Mixin для обработки событий мыши в PageViewer"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QGraphicsRectItem, QMenu
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QColor, QBrush, QWheelEvent

from rd_core.models import BlockType, ShapeType


class MouseEventsMixin:
    """Миксин для обработки событий мыши"""
    
    def wheelEvent(self, event: QWheelEvent):
        """Обработка колеса мыши для масштабирования"""
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        
        # При рисовании полигона центрируем на последней точке
        if self.drawing_polygon and self.polygon_points:
            center_point = self.polygon_points[-1]
        else:
            center_point = self.mapToScene(event.position().toPoint())
        
        self.zoom_factor *= factor
        self.scale(factor, factor)
        
        # Центрируем вид на нужной точке
        self.centerOn(center_point)
        
        # Используем throttled redraw для плавного зума
        if self.current_blocks:
            self._redraw_blocks_throttled(32)
    
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
                    # Если есть единично выбранный блок, добавляем его в множественный выбор
                    if self.selected_block_idx is not None and self.selected_block_idx not in self.selected_block_indices:
                        self.selected_block_indices.append(self.selected_block_idx)
                        self.selected_block_idx = None
                    
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
        elif event.key() == Qt.Key_Left:
            main_window = self.window()
            if hasattr(main_window, 'navigation_manager'):
                main_window.navigation_manager.prev_page()
                return
        elif event.key() == Qt.Key_Right:
            main_window = self.window()
            if hasattr(main_window, 'navigation_manager'):
                main_window.navigation_manager.next_page()
                return
        else:
            super().keyPressEvent(event)

