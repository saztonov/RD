"""Основной миксин контекстного меню PageViewer"""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QMenu

from rd_core.models import BlockType

from app.gui.page_viewer_menus.context_menu.block_operations import BlockOperationsMixin
from app.gui.page_viewer_menus.context_menu.category_mixin import CategoryMixin
from app.gui.page_viewer_menus.context_menu.group_operations import GroupOperationsMixin

logger = logging.getLogger(__name__)


class ContextMenuMixin(CategoryMixin, BlockOperationsMixin, GroupOperationsMixin):
    """Миксин для контекстного меню PageViewer"""

    def contextMenuEvent(self, event):
        """Обработка контекстного меню"""
        if self.selected_block_idx is not None:
            self._show_context_menu(event.globalPos())

    def _show_context_menu(self, global_pos):
        """Показать контекстное меню"""
        if self.read_only:
            return

        menu = QMenu(self)

        selected_blocks = []
        if self.selected_block_indices:
            for idx in self.selected_block_indices:
                selected_blocks.append({"idx": idx})
        elif self.selected_block_idx is not None:
            selected_blocks.append({"idx": self.selected_block_idx})

        if not selected_blocks:
            return

        # 1. Добавить связанные блоки
        self._add_linked_block_action(menu, selected_blocks)

        # 2. Изменить тип
        self._add_change_type_action(menu, selected_blocks)

        # 3. Сгруппировать
        self._add_group_actions(menu, selected_blocks)

        # 4. Удалить
        self._add_delete_action(menu, selected_blocks)

        # 5. Категории изображений
        menu.addSeparator()
        self._add_category_menu(menu, selected_blocks)

        # 6. Корректировочные блоки
        menu.addSeparator()
        self._add_correction_action(menu, selected_blocks)

        menu.exec(global_pos)

    def _add_linked_block_action(self, menu: QMenu, selected_blocks: list):
        """Добавить пункт меню для связанных блоков"""
        if len(selected_blocks) == 1:
            block_idx = selected_blocks[0]["idx"]
            if 0 <= block_idx < len(self.current_blocks):
                block = self.current_blocks[block_idx]
                opposite_type = (
                    BlockType.IMAGE
                    if block.block_type == BlockType.TEXT
                    else BlockType.TEXT
                )
                add_linked_action = menu.addAction(
                    f"🔗 Добавить связанный блок ({opposite_type.value})"
                )
                add_linked_action.triggered.connect(
                    lambda checked, blocks=selected_blocks: self._create_linked_blocks(
                        blocks
                    )
                )
        else:
            add_linked_action = menu.addAction(
                f"🔗 Добавить связанные блоки ({len(selected_blocks)})"
            )
            add_linked_action.triggered.connect(
                lambda checked, blocks=selected_blocks: self._create_linked_blocks(
                    blocks
                )
            )

    def _add_change_type_action(self, menu: QMenu, selected_blocks: list):
        """Добавить пункт меню для изменения типа"""
        block_types = []
        for data in selected_blocks:
            block_idx = data["idx"]
            if 0 <= block_idx < len(self.current_blocks):
                block_types.append(self.current_blocks[block_idx].block_type)

        all_same_type = len(set(block_types)) == 1 if block_types else False

        if all_same_type:
            current_type = block_types[0]
            opposite_type = (
                BlockType.IMAGE if current_type == BlockType.TEXT else BlockType.TEXT
            )
            if len(selected_blocks) == 1:
                change_type_action = menu.addAction(
                    f"Изменить тип → {opposite_type.value}"
                )
            else:
                change_type_action = menu.addAction(
                    f"Изменить типы → {opposite_type.value} ({len(selected_blocks)})"
                )
            change_type_action.triggered.connect(
                lambda checked, blocks=selected_blocks, bt=opposite_type: self._apply_type_to_blocks(
                    blocks, bt
                )
            )
        else:
            type_menu = menu.addMenu(f"Изменить типы ({len(selected_blocks)} блоков)")
            action_text = type_menu.addAction("TEXT")
            action_text.triggered.connect(
                lambda checked, blocks=selected_blocks: self._apply_type_to_blocks(
                    blocks, BlockType.TEXT
                )
            )
            action_image = type_menu.addAction("IMAGE")
            action_image.triggered.connect(
                lambda checked, blocks=selected_blocks: self._apply_type_to_blocks(
                    blocks, BlockType.IMAGE
                )
            )

    def _add_group_actions(self, menu: QMenu, selected_blocks: list):
        """Добавить пункты меню для группировки"""
        if len(selected_blocks) > 1:
            group_action = menu.addAction("📦 Сгруппировать")
            group_action.triggered.connect(lambda: self._group_blocks(selected_blocks))

        main_window = self.parent().window()
        if hasattr(main_window, "selected_group_id") and main_window.selected_group_id:
            add_to_group_action = menu.addAction(
                f"➕ Добавить в группу {main_window.selected_group_id[:8]}..."
            )
            add_to_group_action.triggered.connect(
                lambda: self._add_blocks_to_group(
                    selected_blocks, main_window.selected_group_id
                )
            )

    def _add_delete_action(self, menu: QMenu, selected_blocks: list):
        """Добавить пункт меню для удаления"""
        if len(selected_blocks) == 1:
            delete_action = menu.addAction("🗑️ Удалить")
        else:
            delete_action = menu.addAction(
                f"🗑️ Удалить ({len(selected_blocks)} блоков)"
            )
        delete_action.triggered.connect(
            lambda blocks=selected_blocks: self._delete_blocks(blocks)
        )

    def _add_category_menu(self, menu: QMenu, selected_blocks: list):
        """Добавить подменю категорий изображений"""
        if len(selected_blocks) >= 1:
            block_idx = selected_blocks[0]["idx"]
            if 0 <= block_idx < len(self.current_blocks):
                block = self.current_blocks[block_idx]
                if block.block_type == BlockType.IMAGE:
                    categories = self._get_image_categories()
                    if categories:
                        cat_menu = menu.addMenu("📂 Категория изображения")
                        for cat in categories:
                            cat_name = cat.get("name", "???")
                            cat_id = cat.get("id")
                            cat_code = cat.get("code")

                            prefix = "✓ " if block.category_id == cat_id else "  "
                            if cat.get("is_default"):
                                prefix = "⭐ " if block.category_id == cat_id else "☆ "

                            action = cat_menu.addAction(f"{prefix}{cat_name}")
                            action.triggered.connect(
                                lambda checked, cid=cat_id, ccode=cat_code, blocks=selected_blocks: self._apply_category_to_blocks(
                                    blocks, cid, ccode
                                )
                            )

    def _add_correction_action(self, menu: QMenu, selected_blocks: list):
        """Добавить пункт меню для пометки как корректировочный"""
        if not selected_blocks:
            return

        # Проверяем текущий статус блоков
        all_correction = all(
            self.current_blocks[b["idx"]].is_correction
            for b in selected_blocks
            if 0 <= b["idx"] < len(self.current_blocks)
        )

        if all_correction:
            action_text = "✓ Снять пометку корректировки"
        else:
            action_text = "🔄 Пометить для корректировки"

        if len(selected_blocks) > 1:
            action_text += f" ({len(selected_blocks)})"

        action = menu.addAction(action_text)
        action.triggered.connect(
            lambda checked, blocks=selected_blocks: self._toggle_correction_flag(blocks)
        )
