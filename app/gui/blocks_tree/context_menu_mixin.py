"""Миксин контекстного меню дерева блоков."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from rd_core.models import Block, BlockSource, BlockType

logger = logging.getLogger(__name__)


class ContextMenuMixin:
    """Контекстное меню для дерева блоков."""

    def on_tree_context_menu(self, position):
        """Контекстное меню для дерева блоков"""
        # В режиме read_only не показываем контекстное меню редактирования
        if hasattr(self.parent, "page_viewer") and self.parent.page_viewer.read_only:
            return

        tree = self.parent.sender()
        if tree is None:
            tree = self.blocks_tree
        selected_items = tree.selectedItems()

        selected_blocks = []
        for item in selected_items:
            data = item.data(0, Qt.UserRole)
            if data and isinstance(data, dict) and data.get("type") == "block":
                selected_blocks.append(data)

        if not selected_blocks:
            return

        menu = QMenu(self.parent)

        type_menu = menu.addMenu(f"Применить тип ({len(selected_blocks)} блоков)")
        for block_type in BlockType:
            action = type_menu.addAction(block_type.value)
            action.triggered.connect(
                lambda checked, bt=block_type: self.apply_type_to_blocks(
                    selected_blocks, bt
                )
            )

        # Группировка блоков (если выбрано больше одного блока)
        if len(selected_blocks) > 1:
            menu.addSeparator()
            group_action = menu.addAction("📦 Сгруппировать")
            group_action.triggered.connect(lambda: self.group_blocks(selected_blocks))

        # Добавить в выбранную группу (если есть выбранная группа)
        if hasattr(self.parent, "selected_group_id") and self.parent.selected_group_id:
            add_to_group_action = menu.addAction(f"➕ Добавить в группу")
            add_to_group_action.triggered.connect(
                lambda: self.add_blocks_to_group(
                    selected_blocks, self.parent.selected_group_id
                )
            )

        # Добавить связанный блок (только для одного блока)
        if len(selected_blocks) == 1:
            block = self._get_block(selected_blocks[0])
            if block:
                menu.addSeparator()
                link_menu = menu.addMenu("🔗 Добавить связанный блок")
                for bt in BlockType:
                    if bt != block.block_type:
                        action = link_menu.addAction(f"+ {bt.value}")
                        action.triggered.connect(
                            lambda checked, b=block, data=selected_blocks[
                                0
                            ], target_type=bt: self.create_linked_block(
                                data, target_type
                            )
                        )

        # Проверяем, есть ли IMAGE блоки среди выбранных
        image_blocks = self._filter_image_blocks(selected_blocks)
        if image_blocks:
            menu.addSeparator()
            hint_action = menu.addAction("📝 Назначить подсказку...")
            hint_action.triggered.connect(
                lambda: self.set_hint_for_blocks(image_blocks)
            )

            # Показать текущую подсказку (если один блок выбран)
            if len(image_blocks) == 1:
                block = self._get_block(image_blocks[0])
                if block and block.hint:
                    clear_hint_action = menu.addAction("❌ Очистить подсказку")
                    clear_hint_action.triggered.connect(
                        lambda: self.clear_hint_for_blocks(image_blocks)
                    )

        menu.exec_(tree.viewport().mapToGlobal(position))

    def _filter_image_blocks(self, blocks_data: list) -> list:
        """Отфильтровать только IMAGE блоки"""
        result = []
        if not self.parent.annotation_document:
            return result

        for data in blocks_data:
            page_num = data["page"]
            block_idx = data["idx"]

            if page_num < len(self.parent.annotation_document.pages):
                page = self.parent.annotation_document.pages[page_num]
                if block_idx < len(page.blocks):
                    block = page.blocks[block_idx]
                    if block.block_type == BlockType.IMAGE:
                        result.append(data)
        return result

    def create_linked_block(self, block_data: dict, target_type: BlockType):
        """Создать связанный блок другого типа"""
        if not self.parent.annotation_document:
            return

        page_num = block_data["page"]
        block_idx = block_data["idx"]

        if page_num >= len(self.parent.annotation_document.pages):
            return

        page = self.parent.annotation_document.pages[page_num]
        if block_idx >= len(page.blocks):
            return

        source_block = page.blocks[block_idx]

        # Сохраняем состояние для undo
        if hasattr(self.parent, "_save_undo_state"):
            self.parent._save_undo_state()

        with self.view_state.preserve():
            # Создаём новый блок с теми же координатами
            new_block = Block.create(
                page_index=source_block.page_index,
                coords_px=source_block.coords_px,
                page_width=page.width,
                page_height=page.height,
                block_type=target_type,
                source=BlockSource.USER,
                shape_type=source_block.shape_type,
                polygon_points=source_block.polygon_points,
                linked_block_id=source_block.id,
            )

            # Связываем исходный блок с новым
            source_block.linked_block_id = new_block.id

            # Добавляем новый блок сразу после исходного
            page.blocks.insert(block_idx + 1, new_block)

            # Обновляем UI
            self.parent._render_current_page()

        self.update_blocks_tree()
        if hasattr(self.parent, "_auto_save_annotation"):
            self.parent._auto_save_annotation()

        # Уведомление
        from app.gui.toast import show_toast

        show_toast(self.parent, f"Создан связанный блок: {target_type.value}")
