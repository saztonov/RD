"""Mixin для рендеринга блоков в PageViewer"""
from __future__ import annotations

from typing import Dict, List, Optional, Union

from PySide6.QtCore import QPointF, QRectF, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsTextItem
from shiboken6 import isValid

from rd_domain.models import Block, BlockSource, BlockType, ShapeType


class BlockRenderingMixin:
    """Миксин для отрисовки блоков"""

    _redraw_pending: bool = False
    _last_redraw_time: float = 0
    _redraw_timer: QTimer = None
    _block_hashes: Dict[str, int] = None  # Хеши блоков для детекции изменений

    def set_blocks(self, blocks: List[Block], force_redraw: bool = False):
        """
        Установить список блоков для отображения.

        Использует инкрементальное обновление:
        - Удаляет только отсутствующие блоки
        - Добавляет только новые блоки
        - Обновляет только измененные блоки

        Args:
            blocks: список блоков
            force_redraw: принудительная полная перерисовка
        """
        if self._block_hashes is None:
            self._block_hashes = {}

        new_blocks_by_id = {b.id: b for b in blocks}
        new_ids = set(new_blocks_by_id.keys())
        current_ids = set(self.block_items.keys())

        # Полная перерисовка если force или первая загрузка
        if force_redraw or not current_ids:
            self.current_blocks = blocks
            self._clear_block_items()
            self._block_hashes.clear()
            self._draw_all_blocks()
            return

        # Инкрементальное обновление
        ids_to_remove = current_ids - new_ids
        ids_to_add = new_ids - current_ids
        ids_to_check = current_ids & new_ids

        # 1. Удаляем отсутствующие блоки
        for block_id in ids_to_remove:
            self._remove_block_visual(block_id)

        # Обновляем current_blocks для корректной индексации
        self.current_blocks = blocks

        # 2. Проверяем изменения существующих блоков
        for block_id in ids_to_check:
            block = new_blocks_by_id[block_id]
            block_hash = self._compute_block_hash(block)

            if self._block_hashes.get(block_id) != block_hash:
                # Блок изменился - обновляем
                idx = next((i for i, b in enumerate(blocks) if b.id == block_id), None)
                if idx is not None:
                    self._update_block_visual(block, idx)
                    self._block_hashes[block_id] = block_hash

        # 3. Добавляем новые блоки
        for block_id in ids_to_add:
            block = new_blocks_by_id[block_id]
            idx = next((i for i, b in enumerate(blocks) if b.id == block_id), None)
            if idx is not None:
                self._draw_block(block, idx)
                self._block_hashes[block_id] = self._compute_block_hash(block)

    def _compute_block_hash(self, block: Block) -> int:
        """Вычислить хеш блока для детекции изменений"""
        return hash((
            tuple(block.coords_px),
            block.block_type,
            block.source,
            block.shape_type,
            tuple(block.polygon_points) if block.polygon_points else None,
            block.group_id,
            block.category_code if hasattr(block, 'category_code') else None,
        ))

    def _clear_block_items(self):
        """Очистить все QGraphicsRectItem блоков"""
        for item in self.block_items.values():
            if isValid(item):
                self.scene.removeItem(item)
        self.block_items.clear()
        for label in self.block_labels.values():
            if isValid(label):
                self.scene.removeItem(label)
        self.block_labels.clear()
        self._clear_resize_handles()
        if self._block_hashes:
            self._block_hashes.clear()

    def _remove_block_visual(self, block_id: str):
        """Удалить визуальное представление одного блока"""
        # Удаляем item блока
        if block_id in self.block_items:
            item = self.block_items[block_id]
            if isValid(item):
                self.scene.removeItem(item)
            del self.block_items[block_id]

        # Удаляем метку с номером
        if block_id in self.block_labels:
            label = self.block_labels[block_id]
            if isValid(label):
                self.scene.removeItem(label)
            del self.block_labels[block_id]

        # Удаляем метку галочки для групп
        check_key = block_id + "_check"
        if check_key in self.block_labels:
            check_label = self.block_labels[check_key]
            if isValid(check_label):
                self.scene.removeItem(check_label)
            del self.block_labels[check_key]

        # Удаляем хеш
        if self._block_hashes and block_id in self._block_hashes:
            del self._block_hashes[block_id]

    def _update_block_visual(self, block: Block, idx: int):
        """Обновить визуальное представление блока без пересоздания сцены"""
        # Удаляем старое представление
        self._remove_block_visual(block.id)
        # Рисуем заново
        self._draw_block(block, idx)

    def add_block_visual(self, block: Block):
        """
        Добавить визуальное представление нового блока.
        Используется для real-time добавления от других клиентов.
        """
        if block.id in self.block_items:
            return  # Уже существует

        # Добавляем в current_blocks если еще нет
        if not any(b.id == block.id for b in self.current_blocks):
            self.current_blocks.append(block)

        idx = next((i for i, b in enumerate(self.current_blocks) if b.id == block.id), None)
        if idx is not None:
            self._draw_block(block, idx)
            if self._block_hashes is None:
                self._block_hashes = {}
            self._block_hashes[block.id] = self._compute_block_hash(block)

    def remove_block_visual(self, block_id: str):
        """
        Удалить визуальное представление блока.
        Используется для real-time удаления от других клиентов.
        """
        self._remove_block_visual(block_id)

        # Удаляем из current_blocks
        self.current_blocks = [b for b in self.current_blocks if b.id != block_id]

    def update_block_visual(self, block: Block):
        """
        Обновить визуальное представление блока.
        Используется для real-time обновления от других клиентов.
        """
        # Обновляем в current_blocks
        for i, b in enumerate(self.current_blocks):
            if b.id == block.id:
                self.current_blocks[i] = block
                self._update_block_visual(block, i)
                if self._block_hashes is None:
                    self._block_hashes = {}
                self._block_hashes[block.id] = self._compute_block_hash(block)
                return

        # Если блока не было - добавляем
        self.add_block_visual(block)

    def _draw_all_blocks(self):
        """Отрисовать все блоки"""
        for idx, block in enumerate(self.current_blocks):
            self._draw_block(block, idx)

    def _draw_block(self, block: Block, idx: int):
        """Отрисовать один блок"""
        from PySide6.QtCore import Qt

        color = self._get_block_color(block)
        pen = QPen(color, 2)

        # Блоки в группе имеют красную рамку, но заливка по типу блока
        if block.group_id:
            pen.setColor(QColor(220, 20, 60))  # Crimson
            pen.setWidth(4)

        if block.source == BlockSource.AUTO:
            pen.setStyle(Qt.DashLine)
            pen.setWidth(3)

        if idx in self.selected_block_indices:
            pen.setColor(QColor(0, 120, 255))
            pen.setWidth(4)

        if idx == self.selected_block_idx:
            pen.setWidth(4)

        # Заливка всегда по типу блока (текст/картинка)
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
        # Позиционируем метку в правом верхнем углу блока с учетом масштаба
        offset_x = 5 / self.zoom_factor  # Небольшой отступ внутрь блока
        offset_y = 5 / self.zoom_factor
        label.setPos(x2 - offset_x, y1 + offset_y)
        self.scene.addItem(label)
        self.block_labels[block.id] = label

        # Иконка галочки по центру для блоков в группе
        if block.group_id:
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            check_label = QGraphicsTextItem("✓")
            check_font = QFont("Arial", 16, QFont.Bold)
            check_label.setFont(check_font)
            check_label.setDefaultTextColor(QColor(220, 20, 60))  # Crimson
            check_label.setFlag(
                check_label.GraphicsItemFlag.ItemIgnoresTransformations, True
            )
            # Корректируем позицию с учетом масштаба (центрируем относительно размера символа)
            check_offset_x = 8 / self.zoom_factor
            check_offset_y = 12 / self.zoom_factor
            check_label.setPos(center_x - check_offset_x, center_y - check_offset_y)
            self.scene.addItem(check_label)
            self.block_labels[block.id + "_check"] = check_label

        if idx == self.selected_block_idx:
            if block.shape_type == ShapeType.RECTANGLE:
                rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                self._draw_resize_handles(rect)
            elif block.shape_type == ShapeType.POLYGON and block.polygon_points:
                self._draw_polygon_handles(block.polygon_points)

    def _get_block_color(self, block: Block) -> QColor:
        """Получить цвет для блока с учетом типа и категории"""
        # Если у блока категория "stamp" - синий цвет
        if hasattr(block, "category_code") and block.category_code == "stamp":
            return QColor(30, 144, 255)  # Dodger Blue

        # Иначе цвет по типу блока
        colors = {
            BlockType.TEXT: QColor(0, 255, 0),
            BlockType.IMAGE: QColor(255, 140, 0),
        }
        return colors.get(block.block_type, QColor(128, 128, 128))

    def _redraw_blocks(self):
        """Перерисовать все блоки"""
        self._clear_block_items()
        self._draw_all_blocks()

    def _redraw_blocks_throttled(self, delay_ms: int = 16):
        """Перерисовать блоки с throttle (для анимаций)"""
        if self._redraw_pending:
            return
        self._redraw_pending = True

        if self._redraw_timer is None:
            self._redraw_timer = QTimer()
            self._redraw_timer.setSingleShot(True)
            self._redraw_timer.timeout.connect(self._do_throttled_redraw)

        self._redraw_timer.start(delay_ms)

    def _do_throttled_redraw(self):
        """Выполнить отложенную перерисовку"""
        self._redraw_pending = False
        self._redraw_blocks()

    def _update_single_block_visual(self, block_idx: int):
        """Обновить визуал только одного блока (для перетаскивания)"""
        if block_idx >= len(self.current_blocks):
            return

        block = self.current_blocks[block_idx]

        # Удаляем старый item этого блока
        if block.id in self.block_items:
            old_item = self.block_items[block.id]
            if isValid(old_item):
                self.scene.removeItem(old_item)
            del self.block_items[block.id]

        # Удаляем старую метку
        if block.id in self.block_labels:
            old_label = self.block_labels[block.id]
            if isValid(old_label):
                self.scene.removeItem(old_label)
            del self.block_labels[block.id]

        # Удаляем метку галочки если была
        check_key = block.id + "_check"
        if check_key in self.block_labels:
            check_label = self.block_labels[check_key]
            if isValid(check_label):
                self.scene.removeItem(check_label)
            del self.block_labels[check_key]

        # Очищаем и перерисовываем resize handles для выбранного блока
        self._clear_resize_handles()

        # Рисуем блок заново
        self._draw_block(block, block_idx)

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
