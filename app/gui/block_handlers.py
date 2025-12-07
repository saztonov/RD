"""
Миксин для обработки блоков и событий
"""

from PySide6.QtWidgets import QTreeWidgetItem, QMessageBox
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from app.models import Block, BlockType, BlockSource, Page


class BlockHandlersMixin:
    """Миксин для обработки блоков"""
    
    def _get_or_create_page(self, page_num: int) -> Page:
        """Получить страницу или создать новую"""
        if not self.annotation_document:
            return None
        
        while len(self.annotation_document.pages) <= page_num:
            new_page_num = len(self.annotation_document.pages)
            
            # Приоритет: реальное изображение > get_page_dimensions > fallback
            if new_page_num in self.page_images:
                img = self.page_images[new_page_num]
                page = Page(page_number=new_page_num, width=img.width, height=img.height)
            elif self.pdf_document:
                dims = self.pdf_document.get_page_dimensions(new_page_num)
                if dims:
                    page = Page(page_number=new_page_num, width=dims[0], height=dims[1])
                else:
                    page = Page(page_number=new_page_num, width=595, height=842)
            else:
                page = Page(page_number=new_page_num, width=595, height=842)
            
            self.annotation_document.pages.append(page)
        
        return self.annotation_document.pages[page_num]
    
    def _on_block_drawn(self, x1: int, y1: int, x2: int, y2: int):
        """Обработка завершения рисования блока"""
        if not self.annotation_document:
            return
        
        self._save_undo_state()
        
        checked_action = self.block_type_group.checkedAction()
        block_type = checked_action.data() if checked_action else BlockType.TEXT
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        block = Block.create(
            page_index=self.current_page,
            coords_px=(x1, y1, x2, y2),
            page_width=current_page_data.width,
            page_height=current_page_data.height,
            category=self.active_category,
            block_type=block_type,
            source=BlockSource.USER
        )
        
        current_page_data.blocks.append(block)
        self.page_viewer.set_blocks(current_page_data.blocks)
        self.blocks_tree_manager.update_blocks_tree()
    
    def _on_block_selected(self, block_idx: int):
        """Обработка выбора блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data or not (0 <= block_idx < len(current_page_data.blocks)):
            return
        
        block = current_page_data.blocks[block_idx]
        
        self.category_edit.blockSignals(True)
        self.category_edit.setText(block.category)
        self.category_edit.blockSignals(False)
        
        self.blocks_tree_manager.select_block_in_tree(block_idx)
    
    def _on_blocks_selected(self, block_indices: list):
        """Обработка множественного выбора блоков"""
        if not self.annotation_document or not block_indices:
            return
        
        self.blocks_tree_manager.select_blocks_in_tree(block_indices)
    
    def _on_category_changed(self):
        """Изменение категории выбранного блока"""
        category = self.category_edit.text().strip()
        self.active_category = category
        
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if self.page_viewer.selected_block_idx is not None and \
           0 <= self.page_viewer.selected_block_idx < len(current_page_data.blocks):
            self._save_undo_state()
            block = current_page_data.blocks[self.page_viewer.selected_block_idx]
            block.category = category
            self.blocks_tree_manager.update_blocks_tree()
    
    def _on_block_editing(self, block_idx: int):
        """Обработка двойного клика для редактирования блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            self.page_viewer.selected_block_idx = block_idx
            self._on_block_selected(block_idx)
            self.category_edit.setFocus()
            self.category_edit.selectAll()
    
    def _on_block_deleted(self, block_idx: int):
        """Обработка удаления блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            self._save_undo_state()
            
            self.page_viewer.selected_block_idx = None
            del current_page_data.blocks[block_idx]
            
            self.category_edit.blockSignals(True)
            self.category_edit.setText("")
            self.category_edit.blockSignals(False)
            
            self.page_viewer.set_blocks(current_page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
    
    def _on_blocks_deleted(self, block_indices: list):
        """Обработка удаления множественных блоков"""
        if not self.annotation_document or not block_indices:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        self._save_undo_state()
        
        # Сортируем индексы в обратном порядке для корректного удаления
        sorted_indices = sorted(block_indices, reverse=True)
        
        for block_idx in sorted_indices:
            if 0 <= block_idx < len(current_page_data.blocks):
                del current_page_data.blocks[block_idx]
        
        # Очищаем выделение
        self.page_viewer.selected_block_idx = None
        self.page_viewer.selected_block_indices = []
        
        self.category_edit.blockSignals(True)
        self.category_edit.setText("")
        self.category_edit.blockSignals(False)
        
        self.page_viewer.set_blocks(current_page_data.blocks)
        self.blocks_tree_manager.update_blocks_tree()
    
    def _on_block_moved(self, block_idx: int, x1: int, y1: int, x2: int, y2: int):
        """Обработка перемещения/изменения размера блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[block_idx]
            block.update_coords_px((x1, y1, x2, y2),
                                   current_page_data.width,
                                   current_page_data.height)
    
    def _on_tree_block_clicked(self, item: QTreeWidgetItem, column: int):
        """Клик по блоку в дереве"""
        # Определяем, какое дерево было кликнуто
        tree = self.sender()
        if tree is None:
            tree = self.blocks_tree
        
        # Получаем все выбранные элементы
        selected_items = tree.selectedItems()
        
        # Фильтруем только блоки
        selected_blocks = []
        for sel_item in selected_items:
            sel_data = sel_item.data(0, Qt.UserRole)
            if sel_data and isinstance(sel_data, dict) and sel_data.get("type") == "block":
                selected_blocks.append(sel_data)
        
        if not selected_blocks:
            return
        
        # Если выбрано несколько блоков на одной странице
        if len(selected_blocks) > 1:
            # Проверяем, что все блоки на одной странице
            page_num = selected_blocks[0]["page"]
            if all(b["page"] == page_num for b in selected_blocks):
                # Переключаем страницу если нужно
                if self.current_page != page_num:
                    self.navigation_manager.save_current_zoom()
                    self.current_page = page_num
                    self.navigation_manager.load_page_image(self.current_page)
                    self.navigation_manager.restore_zoom()
                
                current_page_data = self._get_or_create_page(self.current_page)
                self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
                self.page_viewer.fit_to_view()
                
                # Выделяем все блоки
                block_indices = [b["idx"] for b in selected_blocks]
                self.page_viewer.selected_block_indices = block_indices
                self.page_viewer.selected_block_idx = None
                self.page_viewer._redraw_blocks()
                
                self._update_ui()
                return
        
        # Одиночное выделение
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict) or data.get("type") != "block":
            return
        
        page_num = data["page"]
        block_idx = data["idx"]
        
        if self.current_page != page_num:
            self.navigation_manager.save_current_zoom()
        
        self.current_page = page_num
        self.navigation_manager.load_page_image(self.current_page)
        self.navigation_manager.restore_zoom()
        
        current_page_data = self._get_or_create_page(self.current_page)
        self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
        self.page_viewer.fit_to_view()
        
        self.page_viewer.selected_block_idx = block_idx
        self.page_viewer.selected_block_indices = []
        self.page_viewer._redraw_blocks()
        
        self._update_ui()
        self._on_block_selected(block_idx)
    
    def _on_tree_block_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Двойной клик - редактирование категории"""
        data = item.data(0, Qt.UserRole)
        if data and isinstance(data, dict) and data.get("type") == "block":
            self.category_edit.setFocus()
            self.category_edit.selectAll()
    
    def _on_page_changed(self, new_page: int):
        """Обработка запроса смены страницы от viewer"""
        if self.pdf_document and 0 <= new_page < self.pdf_document.page_count:
            self.current_page = new_page
            self._render_current_page()
            self._update_ui()
    
    def _clear_current_page(self):
        """Очистить все блоки с текущей страницы"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data or not current_page_data.blocks:
            QMessageBox.information(self, "Информация", "На странице нет блоков")
            return
        
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить все {len(current_page_data.blocks)} блоков со страницы {self.current_page + 1}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._save_undo_state()
            current_page_data.blocks.clear()
            self.page_viewer.set_blocks([])
            self.blocks_tree_manager.update_blocks_tree()
            QMessageBox.information(self, "Успех", "Разметка страницы очищена")
    
    def _move_block_up(self):
        """Переместить выбранный блок вверх"""
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
        
        if not self.annotation_document or page_num >= len(self.annotation_document.pages):
            return
        
        page = self.annotation_document.pages[page_num]
        
        # Проверяем, можем ли перемещать вверх
        if block_idx <= 0:
            return
        
        self._save_undo_state()
        
        # Меняем местами блоки
        page.blocks[block_idx], page.blocks[block_idx - 1] = page.blocks[block_idx - 1], page.blocks[block_idx]
        
        # Обновляем viewer и tree
        self.page_viewer.set_blocks(page.blocks)
        self.blocks_tree_manager.update_blocks_tree()
        
        # Выбираем новую позицию блока
        self.blocks_tree_manager.select_block_in_tree(block_idx - 1)
        self.page_viewer.selected_block_idx = block_idx - 1
        self.page_viewer._redraw_blocks()
    
    def _move_block_down(self):
        """Переместить выбранный блок вниз"""
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
        
        if not self.annotation_document or page_num >= len(self.annotation_document.pages):
            return
        
        page = self.annotation_document.pages[page_num]
        
        # Проверяем, можем ли перемещать вниз
        if block_idx >= len(page.blocks) - 1:
            return
        
        self._save_undo_state()
        
        # Меняем местами блоки
        page.blocks[block_idx], page.blocks[block_idx + 1] = page.blocks[block_idx + 1], page.blocks[block_idx]
        
        # Обновляем viewer и tree
        self.page_viewer.set_blocks(page.blocks)
        self.blocks_tree_manager.update_blocks_tree()
        
        # Выбираем новую позицию блока
        self.blocks_tree_manager.select_block_in_tree(block_idx + 1)
        self.page_viewer.selected_block_idx = block_idx + 1
        self.page_viewer._redraw_blocks()
    
    def keyPressEvent(self, event):
        """Обработка нажатия клавиш"""
        # Ctrl+Z для отмены
        if event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            self._undo()
            return
        # Ctrl+Y для повтора
        elif event.key() == Qt.Key_Y and event.modifiers() & Qt.ControlModifier:
            self._redo()
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
        if hasattr(self, 'blocks_tree') and hasattr(self, 'blocks_tree_by_category') and \
           obj in (self.blocks_tree, self.blocks_tree_by_category):
            if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key_Delete:
                    current_item = obj.currentItem()
                    if current_item:
                        data = current_item.data(0, Qt.UserRole)
                        if data and isinstance(data, dict) and data.get("type") == "block":
                            page_num = data["page"]
                            block_idx = data["idx"]
                            
                            self.current_page = page_num
                            self.navigation_manager.load_page_image(self.current_page)
                            
                            current_page_data = self._get_or_create_page(self.current_page)
                            self.page_viewer.set_blocks(
                                current_page_data.blocks if current_page_data else [])
                            
                            self._on_block_deleted(block_idx)
                            self._update_ui()
                            return True
        
        return super().eventFilter(obj, event)

