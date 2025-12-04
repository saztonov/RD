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
            if self.pdf_document:
                dims = self.pdf_document.get_page_dimensions(len(self.annotation_document.pages))
                if dims:
                    page = Page(page_number=len(self.annotation_document.pages),
                                width=dims[0], height=dims[1])
                else:
                    page = Page(page_number=len(self.annotation_document.pages),
                                width=595, height=842)
                self.annotation_document.pages.append(page)
        
        return self.annotation_document.pages[page_num]
    
    def _on_block_drawn(self, x1: int, y1: int, x2: int, y2: int):
        """Обработка завершения рисования блока"""
        if not self.annotation_document:
            return
        
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
        
        self.block_type_combo.blockSignals(True)
        self.block_type_combo.setCurrentText(block.block_type.value)
        self.block_type_combo.blockSignals(False)
        
        self.category_edit.blockSignals(True)
        self.category_edit.setText(block.category)
        self.category_edit.blockSignals(False)
        
        self.blocks_tree_manager.select_block_in_tree(block_idx)
    
    def _on_block_type_changed(self, new_type: str):
        """Изменение типа выбранного блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if self.page_viewer.selected_block_idx is not None and \
           0 <= self.page_viewer.selected_block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[self.page_viewer.selected_block_idx]
            try:
                block.block_type = BlockType(new_type)
                self.page_viewer._redraw_blocks()
                self.blocks_tree_manager.update_blocks_tree()
            except ValueError:
                pass
    
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
            self.page_viewer.selected_block_idx = None
            del current_page_data.blocks[block_idx]
            
            self.category_edit.blockSignals(True)
            self.category_edit.setText("")
            self.category_edit.blockSignals(False)
            
            self.block_type_combo.blockSignals(True)
            self.block_type_combo.setCurrentIndex(0)
            self.block_type_combo.blockSignals(False)
            
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
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict) or data.get("type") != "block":
            return
        
        page_num = data["page"]
        block_idx = data["idx"]
        
        if self.current_page != page_num:
            self.page_zoom_states[self.current_page] = (
                self.page_viewer.transform(),
                self.page_viewer.zoom_factor
            )
        
        self.current_page = page_num
        
        if self.current_page in self.page_images:
            self.page_viewer.set_page_image(self.page_images[self.current_page],
                                            self.current_page, reset_zoom=False)
        else:
            img = self.pdf_document.render_page(self.current_page)
            if img:
                self.page_images[self.current_page] = img
                self.page_viewer.set_page_image(img, self.current_page, reset_zoom=False)
        
        if self.current_page in self.page_zoom_states:
            saved_transform, saved_zoom = self.page_zoom_states[self.current_page]
            self.page_viewer.setTransform(saved_transform)
            self.page_viewer.zoom_factor = saved_zoom
        elif self.page_zoom_states:
            last_page = max(self.page_zoom_states.keys())
            saved_transform, saved_zoom = self.page_zoom_states[last_page]
            self.page_viewer.setTransform(saved_transform)
            self.page_viewer.zoom_factor = saved_zoom
        
        current_page_data = self._get_or_create_page(self.current_page)
        self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
        self.page_viewer.fit_to_view()
        
        self.page_viewer.selected_block_idx = block_idx
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
    
    def _edit_type_prompt(self, type_name: str, display_name: str):
        """Редактировать промт для типа блока"""
        default_prompts = {
            "text": "Распознай текст на изображении. Сохрани форматирование и структуру.",
            "table": "Распознай таблицу на изображении. Преобразуй в markdown формат.",
            "image": "Опиши содержимое изображения. Укажи все важные детали."
        }
        self.prompt_manager.edit_prompt(
            type_name,
            f"Промт для типа: {display_name}",
            default_prompts.get(type_name, "")
        )
    
    def _edit_selected_category_prompt(self):
        """Редактировать промт выбранной категории"""
        selected_items = self.categories_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Выберите категорию",
                                    "Сначала выберите категорию из списка")
            return
        category_name = selected_items[0].text()
        self.category_manager.edit_category_prompt(category_name)
    
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
            current_page_data.blocks.clear()
            self.page_viewer.set_blocks([])
            self.blocks_tree_manager.update_blocks_tree()
            QMessageBox.information(self, "Успех", "Разметка страницы очищена")
    
    def keyPressEvent(self, event):
        """Обработка нажатия клавиш"""
        if event.key() == Qt.Key_Left:
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
                            
                            if self.current_page in self.page_images:
                                self.page_viewer.set_page_image(
                                    self.page_images[self.current_page],
                                    self.current_page, reset_zoom=False)
                            else:
                                img = self.pdf_document.render_page(self.current_page)
                                if img:
                                    self.page_images[self.current_page] = img
                                    self.page_viewer.set_page_image(
                                        img, self.current_page, reset_zoom=False)
                            
                            current_page_data = self._get_or_create_page(self.current_page)
                            self.page_viewer.set_blocks(
                                current_page_data.blocks if current_page_data else [])
                            
                            self._on_block_deleted(block_idx)
                            self._update_ui()
                            return True
        
        return super().eventFilter(obj, event)

