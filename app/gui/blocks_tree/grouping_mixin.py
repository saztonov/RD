"""Миксин группировки блоков."""
from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


class GroupingMixin:
    """Группировка блоков и добавление в группы."""

    def group_blocks(self, blocks_data: list):
        """Сгруппировать блоки"""
        if not self.parent.annotation_document:
            return

        # Проверяем, есть ли выбранная группа
        group_id = getattr(self.parent, "selected_group_id", None)
        group_name = None

        if group_id:
            # Берём название существующей группы
            for page in self.parent.annotation_document.pages:
                for block in page.blocks:
                    if block.group_id == group_id and block.group_name:
                        group_name = block.group_name
                        break
                if group_name:
                    break
        else:
            # Показываем немодальный диалог
            from app.gui.group_name_dialog import GroupNameDialog

            dialog = GroupNameDialog(
                self.parent,
                blocks_data,
                lambda data, gid, name: self._apply_group(data, gid, name),
            )
            dialog.show()
            return

        self._apply_group(blocks_data, group_id, group_name)

    def _apply_group(self, blocks_data: list, group_id: str, group_name: str):
        """Применить группировку к блокам"""
        # Сохраняем состояние для undo
        if hasattr(self.parent, "_save_undo_state"):
            self.parent._save_undo_state()

        with self.view_state.preserve():
            # Применяем group_id и group_name ко всем выбранным блокам
            for data in blocks_data:
                page_num = data["page"]
                block_idx = data["idx"]

                if page_num < len(self.parent.annotation_document.pages):
                    page = self.parent.annotation_document.pages[page_num]
                    if block_idx < len(page.blocks):
                        page.blocks[block_idx].group_id = group_id
                        page.blocks[block_idx].group_name = group_name

            # Обновляем UI
            self.parent._render_current_page()

        self.update_blocks_tree()
        if hasattr(self.parent, "_update_groups_tree"):
            self.parent._update_groups_tree()
        if hasattr(self.parent, "_auto_save_annotation"):
            self.parent._auto_save_annotation()

        # Уведомление
        from app.gui.toast import show_toast

        show_toast(self.parent, f"Блоки сгруппированы: {group_name}")

    def add_blocks_to_group(self, blocks_data: list, group_id: str):
        """Добавить блоки в существующую группу"""
        if not self.parent.annotation_document:
            return

        # Находим название группы
        group_name = None
        for page in self.parent.annotation_document.pages:
            for block in page.blocks:
                if block.group_id == group_id and block.group_name:
                    group_name = block.group_name
                    break
            if group_name:
                break

        # Сохраняем состояние для undo
        if hasattr(self.parent, "_save_undo_state"):
            self.parent._save_undo_state()

        with self.view_state.preserve():
            # Применяем group_id и group_name ко всем выбранным блокам
            for data in blocks_data:
                page_num = data["page"]
                block_idx = data["idx"]

                if page_num < len(self.parent.annotation_document.pages):
                    page = self.parent.annotation_document.pages[page_num]
                    if block_idx < len(page.blocks):
                        page.blocks[block_idx].group_id = group_id
                        page.blocks[block_idx].group_name = group_name

            # Обновляем UI
            self.parent._render_current_page()

        self.update_blocks_tree()
        if hasattr(self.parent, "_update_groups_tree"):
            self.parent._update_groups_tree()
        if hasattr(self.parent, "_auto_save_annotation"):
            self.parent._auto_save_annotation()

        # Уведомление
        from app.gui.toast import show_toast

        show_toast(self.parent, f"Блоки добавлены в группу: {group_name}")
