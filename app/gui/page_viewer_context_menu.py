"""Mixin для контекстного меню в PageViewer"""
from __future__ import annotations

import uuid
import logging
from PySide6.QtWidgets import QMenu

from rd_core.models import BlockType, Block, BlockSource

logger = logging.getLogger(__name__)


class ContextMenuMixin:
    """Миксин для контекстного меню"""
    
    # Кэш категорий изображений
    _image_categories_cache = None
    _tree_client = None
    
    def contextMenuEvent(self, event):
        """Обработка контекстного меню"""
        if self.selected_block_idx is not None:
            self._show_context_menu(event.globalPos())
    
    def _get_image_categories(self):
        """Получить категории изображений из кэша или Supabase"""
        if ContextMenuMixin._image_categories_cache is not None:
            return ContextMenuMixin._image_categories_cache
        
        try:
            if ContextMenuMixin._tree_client is None:
                from app.tree_client import TreeClient
                ContextMenuMixin._tree_client = TreeClient()
            
            if ContextMenuMixin._tree_client.is_available():
                ContextMenuMixin._image_categories_cache = ContextMenuMixin._tree_client.get_image_categories()
            else:
                ContextMenuMixin._image_categories_cache = []
        except Exception as e:
            logger.warning(f"Не удалось загрузить категории: {e}")
            ContextMenuMixin._image_categories_cache = []
        
        return ContextMenuMixin._image_categories_cache
    
    @classmethod
    def invalidate_categories_cache(cls):
        """Сбросить кэш категорий"""
        cls._image_categories_cache = None
    
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
        
        # 1. Добавить связанный блок (только для одного блока)
        if len(selected_blocks) == 1:
            block_idx = selected_blocks[0]["idx"]
            if 0 <= block_idx < len(self.current_blocks):
                block = self.current_blocks[block_idx]
                add_linked_action = menu.addAction("🔗 Добавить связанный блок")
                
                # Определяем противоположный тип
                opposite_type = BlockType.IMAGE if block.block_type == BlockType.TEXT else BlockType.TEXT
                add_linked_action.triggered.connect(
                    lambda checked, b=block, target_type=opposite_type: 
                    self._create_linked_block(b, target_type))
        
        # 2. Изменить тип
        if len(selected_blocks) == 1:
            # Для одного блока - сразу меняем на противоположный
            block_idx = selected_blocks[0]["idx"]
            if 0 <= block_idx < len(self.current_blocks):
                block = self.current_blocks[block_idx]
                opposite_type = BlockType.IMAGE if block.block_type == BlockType.TEXT else BlockType.TEXT
                change_type_action = menu.addAction(f"Изменить тип → {opposite_type.value}")
                change_type_action.triggered.connect(
                    lambda checked, blocks=selected_blocks, bt=opposite_type: 
                    self._apply_type_to_blocks(blocks, bt))
        else:
            # Для нескольких блоков - показываем список text/image
            type_menu = menu.addMenu(f"Изменить тип ({len(selected_blocks)} блоков)")
            action_text = type_menu.addAction("TEXT")
            action_text.triggered.connect(lambda checked, blocks=selected_blocks: 
                                         self._apply_type_to_blocks(blocks, BlockType.TEXT))
            action_image = type_menu.addAction("IMAGE")
            action_image.triggered.connect(lambda checked, blocks=selected_blocks: 
                                          self._apply_type_to_blocks(blocks, BlockType.IMAGE))
        
        # 3. Категория изображения
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
                            
                            # Отметка текущей категории
                            prefix = "✓ " if block.category_id == cat_id else "  "
                            if cat.get("is_default"):
                                prefix = "⭐ " if block.category_id == cat_id else "☆ "
                            
                            action = cat_menu.addAction(f"{prefix}{cat_name}")
                            action.triggered.connect(
                                lambda checked, cid=cat_id, ccode=cat_code, blocks=selected_blocks:
                                self._apply_category_to_blocks(blocks, cid, ccode)
                            )
        
        menu.addSeparator()
        
        # Группировка блоков (если выбрано больше одного блока)
        if len(selected_blocks) > 1:
            group_action = menu.addAction("📦 Сгруппировать")
            group_action.triggered.connect(lambda: self._group_blocks(selected_blocks))
        
        # Добавить в выбранную группу (если есть выбранная группа)
        main_window = self.parent().window()
        if hasattr(main_window, 'selected_group_id') and main_window.selected_group_id:
            add_to_group_action = menu.addAction(f"➕ Добавить в группу {main_window.selected_group_id[:8]}...")
            add_to_group_action.triggered.connect(
                lambda: self._add_blocks_to_group(selected_blocks, main_window.selected_group_id))
        
        menu.addSeparator()
        
        # 4. Удалить
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
        
        # Сохраняем текущий зум
        saved_transform = self.transform()
        saved_zoom_factor = self.zoom_factor
        
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
        
        # Восстанавливаем зум
        self.setTransform(saved_transform)
        self.zoom_factor = saved_zoom_factor
        
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
        
        # Сохраняем текущий зум
        saved_transform = self.transform()
        saved_zoom_factor = self.zoom_factor
        
        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                page.blocks[block_idx].block_type = block_type
        
        main_window._render_current_page()
        
        # Восстанавливаем зум
        self.setTransform(saved_transform)
        self.zoom_factor = saved_zoom_factor
        
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()
    
    def _apply_category_to_blocks(self, blocks_data: list, category_id: str, category_code: str):
        """Применить категорию к IMAGE блокам"""
        from PySide6.QtWidgets import QMessageBox
        
        main_window = self.parent().window()
        if not hasattr(main_window, 'annotation_document') or not main_window.annotation_document:
            return
        
        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return
        
        page = main_window.annotation_document.pages[current_page]
        
        # Проверка: на странице может быть только один штамп
        if category_code == 'stamp':
            selected_block_ids = {page.blocks[d["idx"]].id for d in blocks_data if d["idx"] < len(page.blocks)}
            existing_stamps = [b for b in page.blocks if getattr(b, 'category_code', None) == 'stamp' and b.id not in selected_block_ids]
            if existing_stamps:
                QMessageBox.warning(main_window, "Ошибка", "На листе может быть только один штамп")
                return
            if len(blocks_data) > 1:
                QMessageBox.warning(main_window, "Ошибка", "Нельзя назначить категорию 'Штамп' нескольким блокам")
                return
        
        # Сохраняем состояние для undo
        if hasattr(main_window, '_save_undo_state'):
            main_window._save_undo_state()
        
        # Сохраняем текущий зум
        saved_transform = self.transform()
        saved_zoom_factor = self.zoom_factor
        
        count = 0
        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                block = page.blocks[block_idx]
                if block.block_type == BlockType.IMAGE:
                    block.category_id = category_id
                    block.category_code = category_code
                    count += 1
        
        main_window._render_current_page()
        
        # Восстанавливаем зум
        self.setTransform(saved_transform)
        self.zoom_factor = saved_zoom_factor
        
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()
        if hasattr(main_window, '_auto_save_annotation'):
            main_window._auto_save_annotation()
        
        # Уведомление
        if count > 0:
            from app.gui.toast import show_toast
            cat_name = category_code or "default"
            show_toast(main_window, f"Категория установлена: {cat_name}")
    
    def _group_blocks(self, blocks_data: list):
        """Сгруппировать блоки"""
        main_window = self.parent().window()
        if not hasattr(main_window, 'annotation_document') or not main_window.annotation_document:
            return
        
        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return
        
        page = main_window.annotation_document.pages[current_page]
        
        # Проверяем, есть ли выбранная группа
        group_id = getattr(main_window, 'selected_group_id', None)
        group_name = None
        
        if group_id:
            # Берём название существующей группы
            for block in page.blocks:
                if block.group_id == group_id and block.group_name:
                    group_name = block.group_name
                    break
        else:
            # Показываем немодальный диалог
            from app.gui.group_name_dialog import GroupNameDialog
            dialog = GroupNameDialog(
                main_window, blocks_data,
                lambda data, gid, name: self._apply_group_from_context(data, gid, name)
            )
            dialog.show()
            return
        
        self._apply_group_from_context(blocks_data, group_id, group_name)
    
    def _apply_group_from_context(self, blocks_data: list, group_id: str, group_name: str):
        """Применить группировку к блокам из контекстного меню"""
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
        
        # Сохраняем текущий зум
        saved_transform = self.transform()
        saved_zoom_factor = self.zoom_factor
        
        # Применяем group_id и group_name ко всем выбранным блокам
        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                page.blocks[block_idx].group_id = group_id
                page.blocks[block_idx].group_name = group_name
        
        # Обновляем UI
        main_window._render_current_page()
        
        # Восстанавливаем зум
        self.setTransform(saved_transform)
        self.zoom_factor = saved_zoom_factor
        
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()
        if hasattr(main_window, '_update_groups_tree'):
            main_window._update_groups_tree()
        if hasattr(main_window, '_auto_save_annotation'):
            main_window._auto_save_annotation()
        
        # Уведомление
        from app.gui.toast import show_toast
        show_toast(main_window, f"Блоки сгруппированы: {group_name}")
    
    def _add_blocks_to_group(self, blocks_data: list, group_id: str):
        """Добавить блоки в существующую группу"""
        main_window = self.parent().window()
        if not hasattr(main_window, 'annotation_document') or not main_window.annotation_document:
            return
        
        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return
        
        page = main_window.annotation_document.pages[current_page]
        
        # Находим название группы
        group_name = None
        for p in main_window.annotation_document.pages:
            for block in p.blocks:
                if block.group_id == group_id and block.group_name:
                    group_name = block.group_name
                    break
            if group_name:
                break
        
        # Сохраняем состояние для undo
        if hasattr(main_window, '_save_undo_state'):
            main_window._save_undo_state()
        
        # Сохраняем текущий зум
        saved_transform = self.transform()
        saved_zoom_factor = self.zoom_factor
        
        # Применяем group_id и group_name ко всем выбранным блокам
        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                page.blocks[block_idx].group_id = group_id
                page.blocks[block_idx].group_name = group_name
        
        # Обновляем UI
        main_window._render_current_page()
        
        # Восстанавливаем зум
        self.setTransform(saved_transform)
        self.zoom_factor = saved_zoom_factor
        
        if hasattr(main_window, 'blocks_tree_manager'):
            main_window.blocks_tree_manager.update_blocks_tree()
        if hasattr(main_window, '_update_groups_tree'):
            main_window._update_groups_tree()
        if hasattr(main_window, '_auto_save_annotation'):
            main_window._auto_save_annotation()
        
        # Уведомление
        from app.gui.toast import show_toast
        show_toast(main_window, f"Блоки добавлены в группу: {group_name}")



