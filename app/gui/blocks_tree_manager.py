"""
BlocksTreeManager для MainWindow
Управление деревом блоков
"""

import logging
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu
from PySide6.QtCore import Qt
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
                block_item.setText(0, f"Блок {idx + 1}")
                block_item.setText(1, block.block_type.value)
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
        
        menu.exec_(tree.viewport().mapToGlobal(position))
    
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
