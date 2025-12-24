"""Mixin для контекстного меню в PageViewer"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu

from rd_core.models import BlockType, Block, BlockSource


class ContextMenuMixin:
    """Миксин для контекстного меню"""
    
    def contextMenuEvent(self, event):
        """Обработка контекстного меню"""
        if self.selected_block_idx is not None:
            self._show_context_menu(event.globalPos())
    
    def _show_context_menu(self, global_pos):
        """Показать контекстное меню"""
        menu = QMenu(self)
        
        selected_blocks = []
        if self.selected_block_indices:
            for idx in self.selected_block_indices:
                selected_blocks.append({"idx": idx})
        elif self.selected_block_idx is not None:
            selected_blocks.append({"idx": self.selected_block_idx})
        
        if not selected_blocks:
            return
        
        type_menu = menu.addMenu(f"Изменить тип ({len(selected_blocks)} блоков)")
        for block_type in BlockType:
            action = type_menu.addAction(block_type.value)
            action.triggered.connect(lambda checked, bt=block_type, blocks=selected_blocks: 
                                    self._apply_type_to_blocks(blocks, bt))
        
        # Добавить связанный блок (только для одного блока)
        if len(selected_blocks) == 1:
            block_idx = selected_blocks[0]["idx"]
            if 0 <= block_idx < len(self.current_blocks):
                block = self.current_blocks[block_idx]
                link_menu = menu.addMenu("🔗 Добавить связанный блок")
                
                # Показываем типы, отличные от текущего
                for bt in BlockType:
                    if bt != block.block_type:
                        action = link_menu.addAction(f"+ {bt.value}")
                        action.triggered.connect(
                            lambda checked, b=block, target_type=bt: 
                            self._create_linked_block(b, target_type))
        
        menu.addSeparator()
        
        if len(selected_blocks) == 1:
            edit_action = menu.addAction("Редактировать")
            edit_action.triggered.connect(lambda: self.blockEditing.emit(self.selected_block_idx))
        
        delete_action = menu.addAction(f"Удалить ({len(selected_blocks)} блоков)")
        delete_action.triggered.connect(lambda blocks=selected_blocks: self._delete_blocks(blocks))
        
        menu.exec(global_pos)
    
    def _create_linked_block(self, source_block: Block, target_type: BlockType):
        """Создать связанный блок другого типа"""
        main_window = self.parent().window()
        if not hasattr(main_window, 'annotation_document') or not main_window.annotation_document:
            return
        
        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return
        
        page = main_window.annotation_document.pages[current_page]
        
        # Сохраняем состояние для undo
        if hasattr(main_window, '_save_undo_state'):
            main_window._save_undo_state()
        
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
            linked_block_id=source_block.id
        )
        
        # Связываем исходный блок с новым
        source_block.linked_block_id = new_block.id
        
        # Добавляем новый блок сразу после исходного
        source_idx = page.blocks.index(source_block)
        page.blocks.insert(source_idx + 1, new_block)
        
        # Обновляем UI
        main_window._render_current_page()
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()
        if hasattr(main_window, '_auto_save_annotation'):
            main_window._auto_save_annotation()
        
        # Уведомление
        from app.gui.toast import show_toast
        show_toast(main_window, f"Создан связанный блок: {target_type.value}")
    
    def _delete_blocks(self, blocks_data: list):
        """Удалить несколько блоков"""
        if len(blocks_data) == 1:
            self.blockDeleted.emit(blocks_data[0]["idx"])
        else:
            indices = [b["idx"] for b in blocks_data]
            self.blocks_deleted.emit(indices)
    
    def _apply_type_to_blocks(self, blocks_data: list, block_type):
        """Применить тип к нескольким блокам"""
        main_window = self.parent().window()
        if not hasattr(main_window, 'annotation_document') or not main_window.annotation_document:
            return
        
        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return
        
        page = main_window.annotation_document.pages[current_page]
        
        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                page.blocks[block_idx].block_type = block_type
        
        main_window._render_current_page()
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()



