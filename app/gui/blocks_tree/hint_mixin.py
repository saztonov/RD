"""Миксин подсказок для IMAGE блоков."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QInputDialog

logger = logging.getLogger(__name__)


class HintMixin:
    """Назначение и очистка подсказок для IMAGE блоков."""

    def set_hint_for_blocks(self, blocks_data: list):
        """Назначить подсказку для IMAGE блоков"""
        if not self.parent.annotation_document:
            return

        # Получаем текущую подсказку (если один блок)
        current_hint = ""
        if len(blocks_data) == 1:
            block = self._get_block(blocks_data[0])
            if block and block.hint:
                current_hint = block.hint

        # Диалог ввода подсказки
        hint, ok = QInputDialog.getMultiLineText(
            self.parent,
            "Подсказка для изображения",
            "Введите подсказку (описание содержимого блока).\n"
            "Это поможет ИИ лучше распознать изображение.\n\n"
            "Примеры: 'узел крепления', 'штамп', 'план этажа', 'спецификация':",
            current_hint,
        )

        if not ok:
            return

        hint = hint.strip() if hint else None

        with self.view_state.preserve():
            # Применяем подсказку ко всем выбранным IMAGE блокам
            for data in blocks_data:
                page_num = data["page"]
                block_idx = data["idx"]

                if page_num < len(self.parent.annotation_document.pages):
                    page = self.parent.annotation_document.pages[page_num]
                    if block_idx < len(page.blocks):
                        page.blocks[block_idx].hint = hint

            # Обновляем UI
            self.update_blocks_tree()
            self.parent._render_current_page(update_tree=False)

        # Уведомление
        count = len(blocks_data)
        if hint:
            logger.info(f"Подсказка назначена для {count} IMAGE блоков: {hint[:50]}...")
        else:
            logger.info(f"Подсказка очищена для {count} IMAGE блоков")

    def clear_hint_for_blocks(self, blocks_data: list):
        """Очистить подсказку для IMAGE блоков"""
        if not self.parent.annotation_document:
            return

        with self.view_state.preserve():
            for data in blocks_data:
                page_num = data["page"]
                block_idx = data["idx"]

                if page_num < len(self.parent.annotation_document.pages):
                    page = self.parent.annotation_document.pages[page_num]
                    if block_idx < len(page.blocks):
                        page.blocks[block_idx].hint = None

            self.update_blocks_tree()
            self.parent._render_current_page(update_tree=False)

        logger.info(f"Подсказка очищена для {len(blocks_data)} IMAGE блоков")
