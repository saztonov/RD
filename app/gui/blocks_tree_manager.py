"""
BlocksTreeManager для MainWindow
Управление деревом блоков
"""

import logging
import uuid
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QMenu, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt
from rd_core.models import BlockType, Block, BlockSource

logger = logging.getLogger(__name__)


class BlocksTreeManager:
    """Управление деревом блоков"""
    
    _categories_cache = None
    
    def __init__(self, parent, blocks_tree: QTreeWidget):
        self.parent = parent
        self.blocks_tree = blocks_tree
    
    def _get_category_name(self, category_id: str) -> str:
        """Получить название категории по ID"""
        if not category_id:
            return ""
        
        if BlocksTreeManager._categories_cache is None:
            try:
                from app.tree_client import TreeClient
                client = TreeClient()
                if client.is_available():
                    BlocksTreeManager._categories_cache = {
                        cat["id"]: cat["name"] for cat in client.get_image_categories()
                    }
                else:
                    BlocksTreeManager._categories_cache = {}
            except Exception:
                BlocksTreeManager._categories_cache = {}
        
        return BlocksTreeManager._categories_cache.get(category_id, "")
    
    def update_blocks_tree(self):
        """Обновить дерево блоков со всех страниц, группировка по страницам"""
        self.blocks_tree.clear()
        
        if not self.parent.annotation_document:
            return
        
        for page in self.parent.annotation_document.pages:
            page_num = page.page_number
            if not page.blocks:
                continue
            
            page_item = QTreeWidgetItem(self.blocks_tree)
            page_item.setText(0, f"Страница {page_num + 1}")
            page_item.setData(0, Qt.UserRole, {"type": "page", "page": page_num})
            page_item.setExpanded(page_num == self.parent.current_page)

            for idx, block in enumerate(page.blocks):
                block_item = QTreeWidgetItem(page_item)
                # Добавляем индикаторы
                indicators = ""
                # Индикатор связи
                if block.linked_block_id:
                    indicators += " 🔗"
                # Индикатор подсказки для IMAGE блоков
                if block.block_type == BlockType.IMAGE:
                    indicators += " 💡" if block.hint else " 📝"
                block_item.setText(0, f"Блок {idx + 1}{indicators}")
                block_item.setText(1, block.block_type.value)
                # Колонка Категория (для IMAGE блоков)
                cat_name = self._get_category_name(block.category_id) if block.block_type == BlockType.IMAGE else ""
                block_item.setText(2, cat_name)
                # Колонка Группа
                block_item.setText(3, block.group_name or "")
                # Tooltip
                tooltip_parts = []
                if block.group_name:
                    tooltip_parts.append(f"📦 Группа: {block.group_name}")
                if block.linked_block_id:
                    tooltip_parts.append("🔗 Связан с другим блоком")
                if block.hint:
                    tooltip_parts.append(f"Подсказка: {block.hint}")
                if tooltip_parts:
                    block_item.setToolTip(0, "\n".join(tooltip_parts))
                block_item.setData(0, Qt.UserRole, {"type": "block", "page": page_num, "idx": idx})
                block_item.setData(0, Qt.UserRole + 1, idx)
    
    def select_block_in_tree(self, block_idx: int):
        """Выделить блок в дереве"""
        for i in range(self.blocks_tree.topLevelItemCount()):
            page_item = self.blocks_tree.topLevelItem(i)
            page_data = page_item.data(0, Qt.UserRole)
            if not page_data or page_data.get("page") != self.parent.current_page:
                continue
            
            for j in range(page_item.childCount()):
                block_item = page_item.child(j)
                data = block_item.data(0, Qt.UserRole)
                if data and data.get("idx") == block_idx and data.get("page") == self.parent.current_page:
                    self.blocks_tree.setCurrentItem(block_item)
                    return
    
    def select_blocks_in_tree(self, block_indices: list):
        """Выделить несколько блоков в дереве"""
        # Очищаем текущее выделение
        self.blocks_tree.clearSelection()
        
        for i in range(self.blocks_tree.topLevelItemCount()):
            page_item = self.blocks_tree.topLevelItem(i)
            page_data = page_item.data(0, Qt.UserRole)
            if not page_data or page_data.get("page") != self.parent.current_page:
                continue
            
            for j in range(page_item.childCount()):
                block_item = page_item.child(j)
                data = block_item.data(0, Qt.UserRole)
                if data and data.get("idx") in block_indices and data.get("page") == self.parent.current_page:
                    block_item.setSelected(True)
    
    def on_tree_context_menu(self, position):
        """Контекстное меню для дерева блоков"""
        tree = self.parent.sender()
        if tree is None:
            tree = self.blocks_tree
        selected_items = tree.selectedItems()
        
        selected_blocks = []
        for item in selected_items:
            data = item.data(0, Qt.UserRole)
            if data and isinstance(data, dict) and data.get("type") == "block":
                selected_blocks.append(data)
        
        if not selected_blocks:
            return
        
        menu = QMenu(self.parent)
        
        type_menu = menu.addMenu(f"Применить тип ({len(selected_blocks)} блоков)")
        for block_type in BlockType:
            action = type_menu.addAction(block_type.value)
            action.triggered.connect(lambda checked, bt=block_type: self.apply_type_to_blocks(selected_blocks, bt))
        
        # Группировка блоков (если выбрано больше одного блока)
        if len(selected_blocks) > 1:
            menu.addSeparator()
            group_action = menu.addAction("📦 Сгруппировать")
            group_action.triggered.connect(lambda: self.group_blocks(selected_blocks))
        
        # Добавить в выбранную группу (если есть выбранная группа)
        if hasattr(self.parent, 'selected_group_id') and self.parent.selected_group_id:
            add_to_group_action = menu.addAction(f"➕ Добавить в группу")
            add_to_group_action.triggered.connect(
                lambda: self.add_blocks_to_group(selected_blocks, self.parent.selected_group_id))
        
        # Добавить связанный блок (только для одного блока)
        if len(selected_blocks) == 1:
            block = self._get_block(selected_blocks[0])
            if block:
                menu.addSeparator()
                link_menu = menu.addMenu("🔗 Добавить связанный блок")
                for bt in BlockType:
                    if bt != block.block_type:
                        action = link_menu.addAction(f"+ {bt.value}")
                        action.triggered.connect(
                            lambda checked, b=block, data=selected_blocks[0], target_type=bt: 
                            self.create_linked_block(data, target_type))
        
        # Проверяем, есть ли IMAGE блоки среди выбранных
        image_blocks = self._filter_image_blocks(selected_blocks)
        if image_blocks:
            menu.addSeparator()
            hint_action = menu.addAction("📝 Назначить подсказку...")
            hint_action.triggered.connect(lambda: self.set_hint_for_blocks(image_blocks))
            
            # Показать текущую подсказку (если один блок выбран)
            if len(image_blocks) == 1:
                block = self._get_block(image_blocks[0])
                if block and block.hint:
                    clear_hint_action = menu.addAction("❌ Очистить подсказку")
                    clear_hint_action.triggered.connect(lambda: self.clear_hint_for_blocks(image_blocks))
        
        menu.exec_(tree.viewport().mapToGlobal(position))
    
    def _filter_image_blocks(self, blocks_data: list) -> list:
        """Отфильтровать только IMAGE блоки"""
        result = []
        if not self.parent.annotation_document:
            return result
        
        for data in blocks_data:
            page_num = data["page"]
            block_idx = data["idx"]
            
            if page_num < len(self.parent.annotation_document.pages):
                page = self.parent.annotation_document.pages[page_num]
                if block_idx < len(page.blocks):
                    block = page.blocks[block_idx]
                    if block.block_type == BlockType.IMAGE:
                        result.append(data)
        return result
    
    def _get_block(self, data: dict):
        """Получить блок по данным"""
        if not self.parent.annotation_document:
            return None
        
        page_num = data["page"]
        block_idx = data["idx"]
        
        if page_num < len(self.parent.annotation_document.pages):
            page = self.parent.annotation_document.pages[page_num]
            if block_idx < len(page.blocks):
                return page.blocks[block_idx]
        return None
    
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
            current_hint
        )
        
        if not ok:
            return
        
        hint = hint.strip() if hint else None
        
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
    
    def apply_type_to_blocks(self, blocks_data: list, block_type: BlockType):
        """Применить тип к нескольким блокам"""
        if not self.parent.annotation_document:
            return
        
        for data in blocks_data:
            page_num = data["page"]
            block_idx = data["idx"]
            
            if page_num < len(self.parent.annotation_document.pages):
                page = self.parent.annotation_document.pages[page_num]
                if block_idx < len(page.blocks):
                    page.blocks[block_idx].block_type = block_type
        
        self.parent._render_current_page()
        self.update_blocks_tree()
    
    def create_linked_block(self, block_data: dict, target_type: BlockType):
        """Создать связанный блок другого типа"""
        if not self.parent.annotation_document:
            return
        
        page_num = block_data["page"]
        block_idx = block_data["idx"]
        
        if page_num >= len(self.parent.annotation_document.pages):
            return
        
        page = self.parent.annotation_document.pages[page_num]
        if block_idx >= len(page.blocks):
            return
        
        source_block = page.blocks[block_idx]
        
        # Сохраняем состояние для undo
        if hasattr(self.parent, '_save_undo_state'):
            self.parent._save_undo_state()
        
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
        page.blocks.insert(block_idx + 1, new_block)
        
        # Обновляем UI
        self.parent._render_current_page()
        self.update_blocks_tree()
        if hasattr(self.parent, '_auto_save_annotation'):
            self.parent._auto_save_annotation()
        
        # Уведомление
        from app.gui.toast import show_toast
        show_toast(self.parent, f"Создан связанный блок: {target_type.value}")
    
    def group_blocks(self, blocks_data: list):
        """Сгруппировать блоки"""
        if not self.parent.annotation_document:
            return
        
        # Проверяем, есть ли выбранная группа
        group_id = getattr(self.parent, 'selected_group_id', None)
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
                self.parent, blocks_data,
                lambda data, gid, name: self._apply_group(data, gid, name)
            )
            dialog.show()
            return
        
        self._apply_group(blocks_data, group_id, group_name)
    
    def _apply_group(self, blocks_data: list, group_id: str, group_name: str):
        """Применить группировку к блокам"""
        # Сохраняем состояние для undo
        if hasattr(self.parent, '_save_undo_state'):
            self.parent._save_undo_state()
        
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
        if hasattr(self.parent, '_update_groups_tree'):
            self.parent._update_groups_tree()
        if hasattr(self.parent, '_auto_save_annotation'):
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
        if hasattr(self.parent, '_save_undo_state'):
            self.parent._save_undo_state()
        
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
        if hasattr(self.parent, '_update_groups_tree'):
            self.parent._update_groups_tree()
        if hasattr(self.parent, '_auto_save_annotation'):
            self.parent._auto_save_annotation()
        
        # Уведомление
        from app.gui.toast import show_toast
        show_toast(self.parent, f"Блоки добавлены в группу: {group_name}")
