"""Миксин для модификации блоков (удаление, перемещение)"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


class BlockModificationMixin:
    """Миксин для операций модификации блоков"""

    def _on_block_deleted(self, block_idx: int):
        """Обработка удаления блока"""
        if not self.annotation_document:
            return

        # Проверка блокировки документа
        if self._check_document_locked_for_editing():
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return

        if 0 <= block_idx < len(current_page_data.blocks):
            self._save_undo_state()

            # Получаем удаляемый блок
            deleted_block = current_page_data.blocks[block_idx]
            deleted_block_id = deleted_block.id

            # Очищаем связи: если у других блоков есть ссылка на удаляемый блок
            for page in self.annotation_document.pages:
                for block in page.blocks:
                    if block.linked_block_id == deleted_block_id:
                        block.linked_block_id = None

            self.page_viewer.selected_block_idx = None
            del current_page_data.blocks[block_idx]

            self.page_viewer.set_blocks(current_page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()

            # Авто-сохранение разметки
            self._auto_save_annotation()

    def _on_blocks_deleted(self, block_indices: list):
        """Обработка удаления множественных блоков"""
        if not self.annotation_document or not block_indices:
            return

        # Проверка блокировки документа
        if self._check_document_locked_for_editing():
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return

        self._save_undo_state()

        # Собираем ID удаляемых блоков
        deleted_block_ids = set()
        for block_idx in block_indices:
            if 0 <= block_idx < len(current_page_data.blocks):
                deleted_block_ids.add(current_page_data.blocks[block_idx].id)

        # Очищаем связи: если у блоков есть ссылки на удаляемые блоки
        for page in self.annotation_document.pages:
            for block in page.blocks:
                if block.linked_block_id in deleted_block_ids:
                    block.linked_block_id = None

        # Сортируем индексы в обратном порядке для корректного удаления
        sorted_indices = sorted(block_indices, reverse=True)

        for block_idx in sorted_indices:
            if 0 <= block_idx < len(current_page_data.blocks):
                del current_page_data.blocks[block_idx]

        # Очищаем выделение
        self.page_viewer.selected_block_idx = None
        self.page_viewer.selected_block_indices = []

        self.page_viewer.set_blocks(current_page_data.blocks)
        self.blocks_tree_manager.update_blocks_tree()

        # Авто-сохранение разметки
        self._auto_save_annotation()

    def _on_block_moved(self, block_idx: int, x1: int, y1: int, x2: int, y2: int):
        """Обработка перемещения/изменения размера блока"""
        if not self.annotation_document:
            return

        # Проверка блокировки документа
        if self._check_document_locked_for_editing():
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return

        if 0 <= block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[block_idx]
            block.update_coords_px(
                (x1, y1, x2, y2), current_page_data.width, current_page_data.height
            )

            # Авто-сохранение разметки
            self._auto_save_annotation()

    def _clear_current_page(self):
        """Очистить все блоки с текущей страницы"""
        if not self.annotation_document:
            return

        # Проверка блокировки документа
        if self._check_document_locked_for_editing():
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data or not current_page_data.blocks:
            QMessageBox.information(self, "Информация", "На странице нет блоков")
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить все {len(current_page_data.blocks)} блоков "
            f"со страницы {self.current_page + 1}?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self._save_undo_state()

            # Собираем ID всех удаляемых блоков
            deleted_block_ids = {block.id for block in current_page_data.blocks}

            # Очищаем связи
            for page in self.annotation_document.pages:
                for block in page.blocks:
                    if block.linked_block_id in deleted_block_ids:
                        block.linked_block_id = None

            current_page_data.blocks.clear()
            self.page_viewer.set_blocks([])
            self.blocks_tree_manager.update_blocks_tree()
            self._auto_save_annotation()
            from app.gui.toast import show_toast

            show_toast(self, "Разметка страницы очищена")

    def _move_block_up(self):
        """Переместить выбранный блок вверх"""
        # Проверка блокировки документа
        if self._check_document_locked_for_editing():
            return

        tree = self.blocks_tabs.currentWidget()
        if tree is None:
            return

        current_item = tree.currentItem()
        if not current_item:
            return

        data = current_item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict) or data.get("type") != "block":
            return

        page_num = data["page"]
        block_idx = data["idx"]

        if not self.annotation_document or page_num >= len(
            self.annotation_document.pages
        ):
            return

        page = self.annotation_document.pages[page_num]

        # Проверяем, можем ли перемещать вверх
        if block_idx <= 0:
            return

        self._save_undo_state()

        # Меняем местами блоки
        page.blocks[block_idx], page.blocks[block_idx - 1] = (
            page.blocks[block_idx - 1],
            page.blocks[block_idx],
        )

        # Обновляем viewer и tree
        self.page_viewer.set_blocks(page.blocks)
        self.blocks_tree_manager.update_blocks_tree()

        # Выбираем новую позицию блока
        self.blocks_tree_manager.select_block_in_tree(block_idx - 1)
        self.page_viewer.selected_block_idx = block_idx - 1
        self.page_viewer._redraw_blocks()

        self._auto_save_annotation()

    def _move_block_down(self):
        """Переместить выбранный блок вниз"""
        # Проверка блокировки документа
        if self._check_document_locked_for_editing():
            return

        tree = self.blocks_tabs.currentWidget()
        if tree is None:
            return

        current_item = tree.currentItem()
        if not current_item:
            return

        data = current_item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict) or data.get("type") != "block":
            return

        page_num = data["page"]
        block_idx = data["idx"]

        if not self.annotation_document or page_num >= len(
            self.annotation_document.pages
        ):
            return

        page = self.annotation_document.pages[page_num]

        # Проверяем, можем ли перемещать вниз
        if block_idx >= len(page.blocks) - 1:
            return

        self._save_undo_state()

        # Меняем местами блоки
        page.blocks[block_idx], page.blocks[block_idx + 1] = (
            page.blocks[block_idx + 1],
            page.blocks[block_idx],
        )

        # Обновляем viewer и tree
        self.page_viewer.set_blocks(page.blocks)
        self.blocks_tree_manager.update_blocks_tree()

        # Выбираем новую позицию блока
        self.blocks_tree_manager.select_block_in_tree(block_idx + 1)
        self.page_viewer.selected_block_idx = block_idx + 1
        self.page_viewer._redraw_blocks()

        self._auto_save_annotation()
