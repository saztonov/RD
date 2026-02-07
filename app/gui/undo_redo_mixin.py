"""Миксин Undo/Redo для MainWindow."""

import copy
import logging

logger = logging.getLogger(__name__)


class UndoRedoMixin:
    """Операции отмены/повтора действий с блоками."""

    def _save_undo_state(self):
        """Сохранить текущее состояние блоков для отмены"""
        if not self.annotation_document:
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return

        # Делаем глубокую копию блоков
        blocks_copy = copy.deepcopy(current_page_data.blocks)

        # Добавляем в стек undo
        self.undo_stack.append((self.current_page, blocks_copy))

        # Ограничиваем размер стека (последние 50 операций)
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

        # Очищаем стек redo при новом действии
        self.redo_stack.clear()

    def _undo(self):
        """Отменить последнее действие"""
        if not self.undo_stack:
            return

        if not self.annotation_document:
            return

        # Сохраняем текущее состояние в redo
        current_page_data = self._get_or_create_page(self.current_page)
        if current_page_data:
            blocks_copy = copy.deepcopy(current_page_data.blocks)
            self.redo_stack.append((self.current_page, blocks_copy))

        # Восстанавливаем состояние из undo
        page_num, blocks_copy = self.undo_stack.pop()

        # Переключаемся на нужную страницу если надо
        if page_num != self.current_page:
            self.navigation_manager.save_current_zoom()
            self.current_page = page_num
            self.navigation_manager.load_page_image(self.current_page)
            self.navigation_manager.restore_zoom()

        # Восстанавливаем блоки
        page_data = self._get_or_create_page(page_num)
        if page_data:
            page_data.blocks = copy.deepcopy(blocks_copy)
            self.page_viewer.set_blocks(page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
            self._update_ui()

    def _redo(self):
        """Повторить отменённое действие"""
        if not self.redo_stack:
            return

        if not self.annotation_document:
            return

        # Сохраняем текущее состояние в undo
        current_page_data = self._get_or_create_page(self.current_page)
        if current_page_data:
            blocks_copy = copy.deepcopy(current_page_data.blocks)
            self.undo_stack.append((self.current_page, blocks_copy))

        # Восстанавливаем состояние из redo
        page_num, blocks_copy = self.redo_stack.pop()

        # Переключаемся на нужную страницу если надо
        if page_num != self.current_page:
            self.navigation_manager.save_current_zoom()
            self.current_page = page_num
            self.navigation_manager.load_page_image(self.current_page)
            self.navigation_manager.restore_zoom()

        # Восстанавливаем блоки
        page_data = self._get_or_create_page(page_num)
        if page_data:
            page_data.blocks = copy.deepcopy(blocks_copy)
            self.page_viewer.set_blocks(page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
            self._update_ui()
