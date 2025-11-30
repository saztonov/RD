"""
BlocksTreeManager для MainWindow
Управление деревом блоков (два режима отображения)
"""

import logging
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QMessageBox, QInputDialog, QMenu
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from app.models import BlockType

logger = logging.getLogger(__name__)


class BlocksTreeManager:
    """Управление деревом блоков"""
    
    def __init__(self, parent, blocks_tree: QTreeWidget, blocks_tree_by_category: QTreeWidget):
        self.parent = parent
        self.blocks_tree = blocks_tree
        self.blocks_tree_by_category = blocks_tree_by_category
    
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
            
            categories = {}
            for idx, block in enumerate(page.blocks):
                cat = block.category if block.category else "(Без категории)"
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((idx, block))
            
            for cat_name in sorted(categories.keys()):
                cat_item = QTreeWidgetItem(page_item)
                cat_item.setText(0, cat_name)
                cat_item.setData(0, Qt.UserRole, {"type": "category", "page": page_num})
                cat_item.setExpanded(True)
                
                for idx, block in categories[cat_name]:
                    block_item = QTreeWidgetItem(cat_item)
                    block_item.setText(0, f"Блок {idx + 1}")
                    block_item.setText(1, block.block_type.value)
                    block_item.setData(0, Qt.UserRole, {"type": "block", "page": page_num, "idx": idx})
        
        self.update_blocks_tree_by_category()
    
    def update_blocks_tree_by_category(self):
        """Обновить дерево блоков со всех страниц, группировка по категориям"""
        self.blocks_tree_by_category.clear()
        
        if not self.parent.annotation_document:
            return
        
        categories = {}
        for page in self.parent.annotation_document.pages:
            page_num = page.page_number
            for idx, block in enumerate(page.blocks):
                cat = block.category if block.category else "(Без категории)"
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((page_num, idx, block))
        
        for cat_name in sorted(categories.keys()):
            cat_item = QTreeWidgetItem(self.blocks_tree_by_category)
            cat_item.setText(0, cat_name)
            cat_item.setData(0, Qt.UserRole, {"type": "category"})
            cat_item.setExpanded(True)
            
            for page_num, idx, block in categories[cat_name]:
                block_item = QTreeWidgetItem(cat_item)
                block_item.setText(0, f"Блок {idx + 1} (стр. {page_num + 1})")
                block_item.setText(1, block.block_type.value)
                block_item.setData(0, Qt.UserRole, {"type": "block", "page": page_num, "idx": idx})
    
    def select_block_in_tree(self, block_idx: int):
        """Выделить блок в дереве"""
        for i in range(self.blocks_tree.topLevelItemCount()):
            page_item = self.blocks_tree.topLevelItem(i)
            page_data = page_item.data(0, Qt.UserRole)
            if not page_data or page_data.get("page") != self.parent.current_page:
                continue
            
            for j in range(page_item.childCount()):
                cat_item = page_item.child(j)
                for k in range(cat_item.childCount()):
                    block_item = cat_item.child(k)
                    data = block_item.data(0, Qt.UserRole)
                    if data and data.get("idx") == block_idx and data.get("page") == self.parent.current_page:
                        self.blocks_tree.setCurrentItem(block_item)
                        break
        
        for i in range(self.blocks_tree_by_category.topLevelItemCount()):
            cat_item = self.blocks_tree_by_category.topLevelItem(i)
            for j in range(cat_item.childCount()):
                block_item = cat_item.child(j)
                data = block_item.data(0, Qt.UserRole)
                if data and data.get("idx") == block_idx and data.get("page") == self.parent.current_page:
                    self.blocks_tree_by_category.setCurrentItem(block_item)
                    return
    
    def on_tree_context_menu(self, position):
        """Контекстное меню для дерева блоков"""
        tree = self.parent.sender()
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
        
        cat_menu = menu.addMenu(f"Применить категорию ({len(selected_blocks)} блоков)")
        for cat in sorted(self.parent.categories):
            action = cat_menu.addAction(cat)
            action.triggered.connect(lambda checked, c=cat: self.apply_category_to_blocks(selected_blocks, c))
        
        new_cat_action = cat_menu.addAction("Новая категория...")
        new_cat_action.triggered.connect(lambda: self.apply_new_category_to_blocks(selected_blocks))
        
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
        QMessageBox.information(self.parent, "Успех", f"Тип '{block_type.value}' применён к {len(blocks_data)} блокам")
    
    def apply_category_to_blocks(self, blocks_data: list, category: str):
        """Применить категорию к нескольким блокам"""
        if not self.parent.annotation_document:
            return
        
        for data in blocks_data:
            page_num = data["page"]
            block_idx = data["idx"]
            
            if page_num < len(self.parent.annotation_document.pages):
                page = self.parent.annotation_document.pages[page_num]
                if block_idx < len(page.blocks):
                    page.blocks[block_idx].category = category
        
        self.parent._render_current_page()
        self.update_blocks_tree()
        QMessageBox.information(self.parent, "Успех", f"Категория '{category}' применена к {len(blocks_data)} блокам")
    
    def apply_new_category_to_blocks(self, blocks_data: list):
        """Применить новую категорию к нескольким блокам"""
        text, ok = QInputDialog.getText(self.parent, "Новая категория", "Введите название категории:")
        if not ok or not text.strip():
            return
        
        category = text.strip()
        
        if category and category not in self.parent.categories:
            self.parent.categories.append(category)
            self.parent.category_manager.update_categories_list()
        
        self.apply_category_to_blocks(blocks_data, category)

