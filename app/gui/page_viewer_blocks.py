"""Mixin для рендеринга блоков в PageViewer"""
from __future__ import annotations

from typing import List, Dict, Union, Optional

from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsPolygonItem, QGraphicsTextItem
from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QPen, QColor, QBrush, QFont, QPolygonF

from rd_core.models import Block, BlockType, BlockSource, ShapeType


class BlockRenderingMixin:
    """Миксин для отрисовки блоков"""
    
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
        from PySide6.QtCore import Qt
        
        color = self._get_block_color(block.block_type)
        pen = QPen(color, 2)
        
        # Блоки в группе имеют фиолетовую рамку
        if block.group_id:
            pen.setColor(QColor(138, 43, 226))  # BlueViolet
            pen.setWidth(3)
        
        if block.source == BlockSource.AUTO:
            pen.setStyle(Qt.DashLine)
            pen.setWidth(3)
        
        if idx in self.selected_block_indices:
            pen.setColor(QColor(0, 120, 255))
            pen.setWidth(4)
        
        if idx == self.selected_block_idx:
            pen.setWidth(4)
        
        # Цвет заливки: фиолетовый для групп, стандартный для остальных
        fill_color = QColor(138, 43, 226, 25) if block.group_id else QColor(color.red(), color.green(), color.blue(), 30)
        brush = QBrush(fill_color)
        
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
            BlockType.IMAGE: QColor(255, 140, 0),
        }
        return colors.get(block_type, QColor(128, 128, 128))
    
    def _redraw_blocks(self):
        """Перерисовать все блоки"""
        self._clear_block_items()
        self._draw_all_blocks()
    
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



