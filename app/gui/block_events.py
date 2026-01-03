"""Миксин для обработки событий клавиатуры блоков"""

import logging

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

logger = logging.getLogger(__name__)


class BlockEventsMixin:
    """Миксин для обработки событий клавиатуры"""

    def keyPressEvent(self, event):
        """Обработка нажатия клавиш"""
        # В режиме read_only блокируем все команды редактирования
        is_read_only = hasattr(self, "page_viewer") and self.page_viewer.read_only

        # Ctrl+Z для отмены
        if event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            if not is_read_only:
                self._undo()
            return
        # Ctrl+Y для повтора
        elif event.key() == Qt.Key_Y and event.modifiers() & Qt.ControlModifier:
            if not is_read_only:
                self._redo()
            return
        # Ctrl+G для группировки
        elif event.key() == Qt.Key_G and event.modifiers() & Qt.ControlModifier:
            if not is_read_only:
                self._group_selected_blocks()
            return
        elif event.key() == Qt.Key_Left:
            self._prev_page()
            return
        elif event.key() == Qt.Key_Right:
            self._next_page()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        """Обработка событий для деревьев блоков"""
        if hasattr(self, "blocks_tree") and obj is self.blocks_tree:
            if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key_Delete:
                    # В режиме read_only не разрешаем удаление
                    if hasattr(self, "page_viewer") and self.page_viewer.read_only:
                        return True

                    current_item = obj.currentItem()
                    if current_item:
                        data = current_item.data(0, Qt.UserRole)
                        if (
                            data
                            and isinstance(data, dict)
                            and data.get("type") == "block"
                        ):
                            page_num = data["page"]
                            block_idx = data["idx"]

                            self.current_page = page_num
                            self.navigation_manager.load_page_image(self.current_page)

                            current_page_data = self._get_or_create_page(
                                self.current_page
                            )
                            self.page_viewer.set_blocks(
                                current_page_data.blocks if current_page_data else []
                            )

                            self._on_block_deleted(block_idx)
                            self._update_ui()
                            return True

        return super().eventFilter(obj, event)
