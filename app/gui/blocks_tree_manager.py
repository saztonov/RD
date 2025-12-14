"""
BlocksTreeManager для MainWindow
Управление деревом блоков
"""

import logging
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QMenu, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from rd_core.models import BlockType

logger = logging.getLogger(__name__)


class BlocksTreeManager:
    """Управление деревом блоков"""
    
    def __init__(self, parent, blocks_tree: QTreeWidget):
        self.parent = parent
        self.blocks_tree = blocks_tree
    
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
                # Добавляем индикатор подсказки для IMAGE блоков
                hint_indicator = ""
                if block.block_type == BlockType.IMAGE:
                    hint_indicator = " 💡" if block.hint else " 📝"
                block_item.setText(0, f"Блок {idx + 1}{hint_indicator}")
                block_item.setText(1, block.block_type.value)
                # Tooltip с подсказкой
                if block.hint:
                    block_item.setToolTip(0, f"Подсказка: {block.hint}")
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
