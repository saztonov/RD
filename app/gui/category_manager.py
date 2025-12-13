"""
CategoryManager для MainWindow
Управление категориями блоков
"""

import json
import logging
from PySide6.QtWidgets import QListWidget, QMessageBox, QInputDialog, QFileDialog, QListWidgetItem
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

logger = logging.getLogger(__name__)


class CategoryManager:
    """Управление категориями"""
    
    # Стандартные категории для типов блоков
    STANDARD_CATEGORIES = ["Текст", "Таблица", "Картинка"]
    
    def __init__(self, parent, categories_list: QListWidget):
        self.parent = parent
        self.categories_list = categories_list
        self._ensure_standard_categories()
        self._load_categories_from_r2()
        self.update_categories_list()
    
    def _ensure_standard_categories(self):
        """Добавить стандартные категории если их нет"""
        for cat in self.STANDARD_CATEGORIES:
            if cat not in self.parent.categories:
                self.parent.categories.append(cat)
    
    def _load_categories_from_r2(self):
        """Загрузить категории из R2 при инициализации"""
        if hasattr(self.parent, 'prompt_manager'):
            categories_from_r2 = self.parent.prompt_manager.load_categories_from_r2()
            if categories_from_r2:
                self.parent.categories = categories_from_r2
                logger.info(f"✅ Загружено {len(categories_from_r2)} категорий из R2")
    
    def update_categories_list(self):
        """Обновить список категорий"""
        self.categories_list.clear()
        for cat in sorted(self.parent.categories):
            self.categories_list.addItem(cat)
        
        # Обновляем таблицу промтов
        if hasattr(self.parent, 'update_prompts_table'):
            self.parent.update_prompts_table()
    
    def on_category_clicked(self, item):
        """Применить категорию к выбранному блоку при клике"""
        category = item.text()
        
        self.parent.active_category = category
        self.parent.category_edit.blockSignals(True)
        self.parent.category_edit.setText(category)
        self.parent.category_edit.blockSignals(False)
        
        if self.parent.annotation_document and self.parent.page_viewer.selected_block_idx is not None:
            self.apply_category_to_selected_block(category)
    
    def apply_category_to_selected_block(self, category: str):
        """Применить категорию к выбранному блоку"""
        if not self.parent.annotation_document:
            return
        
        current_page_data = self.parent._get_or_create_page(self.parent.current_page)
        if not current_page_data:
            return
        
        if self.parent.page_viewer.selected_block_idx is not None and \
           0 <= self.parent.page_viewer.selected_block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[self.parent.page_viewer.selected_block_idx]
            block.category = category
            
            self.parent.category_edit.blockSignals(True)
            self.parent.category_edit.setText(category)
            self.parent.category_edit.blockSignals(False)
            
            self.parent.blocks_tree_manager.update_blocks_tree()
    
    def add_category(self):
        """Добавить новую категорию"""
        text = self.parent.category_edit.text().strip()
        if not text:
            text, ok = QInputDialog.getText(self.parent, "Новая категория", "Введите название категории:")
            if not ok or not text.strip():
                return
            text = text.strip()
        
        if text and text not in self.parent.categories:
            self.parent.categories.append(text)
            self.update_categories_list()
            
            # Создаем placeholder промт в R2 для новой категории
            if hasattr(self.parent, 'prompt_manager'):
                default_prompt = {
                    "system": "You are an expert document analyzer. Extract and structure information accurately.",
                    "user": f"Analyze this '{text}' block. Extract all relevant information and format it clearly."
                }
                prompt_name = self.parent.prompt_manager.get_category_prompt_name(text)
                self.parent.prompt_manager.save_prompt(prompt_name, default_prompt)
            
            # Сохраняем обновленный список категорий в R2
            self._save_categories_to_r2()
        
        self.parent.active_category = text
        
        if self.parent.page_viewer.selected_block_idx is not None:
            self.apply_category_to_selected_block(text)
    
    def _save_categories_to_r2(self):
        """Сохранить список категорий в R2"""
        if hasattr(self.parent, 'prompt_manager'):
            self.parent.prompt_manager.save_categories_to_r2(self.parent.categories)
    
    def delete_category(self, category_name: str):
        """Удалить категорию и её промт из R2"""
        from PySide6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self.parent,
            "Удаление категории",
            f"Удалить категорию '{category_name}' и её промт из R2?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Удаляем из списка
            if category_name in self.parent.categories:
                self.parent.categories.remove(category_name)
            
            # Удаляем промт из R2
            if hasattr(self.parent, 'prompt_manager'):
                prompt_name = self.parent.prompt_manager.get_category_prompt_name(category_name)
                self.parent.prompt_manager.delete_prompt(prompt_name)
            
            # Сохраняем обновленный список в R2
            self._save_categories_to_r2()
            self.update_categories_list()
            
            from app.gui.toast import show_toast
            show_toast(self.parent, f"Категория удалена: {category_name}")
    
    def edit_category_prompt(self, category_name: str):
        """Редактировать промт категории"""
        if not hasattr(self.parent, 'prompt_manager'):
            QMessageBox.warning(self.parent, "Ошибка", "PromptManager не инициализирован")
            return
        
        prompt_name = self.parent.prompt_manager.get_category_prompt_name(category_name)
        default_prompt = {
            "system": "You are an expert document analyzer. Extract and structure information accurately.",
            "user": f"Analyze this '{category_name}' block. Extract all relevant information."
        }
        self.parent.prompt_manager.edit_prompt(
            prompt_name,
            f"Редактирование промпта: {category_name}",
            default_prompt
        )
    
    def extract_categories_from_document(self):
        """Извлечь все категории из документа"""
        if not self.parent.annotation_document:
            return
        
        categories_set = set()
        for page in self.parent.annotation_document.pages:
            for block in page.blocks:
                if block.category and block.category.strip():
                    categories_set.add(block.category.strip())
        
        for cat in categories_set:
            if cat not in self.parent.categories:
                self.parent.categories.append(cat)
        
        self.update_categories_list()
    
    def export_categories(self):
        """Экспортировать список категорий в JSON"""
        if not self.parent.categories:
            QMessageBox.information(self.parent, "Информация", "Нет категорий для экспорта")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(self.parent, "Экспорт категорий", "categories.json", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({"categories": self.parent.categories}, f, ensure_ascii=False, indent=2)
                from app.gui.toast import show_toast
                show_toast(self.parent, f"Экспортировано {len(self.parent.categories)} категорий")
            except Exception as e:
                QMessageBox.critical(self.parent, "Ошибка", f"Ошибка экспорта:\n{e}")
    
    def import_categories(self):
        """Импортировать список категорий из JSON"""
        file_path, _ = QFileDialog.getOpenFileName(self.parent, "Импорт категорий", "", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                imported = data.get("categories", [])
                
                new_count = 0
                for cat in imported:
                    if cat and cat not in self.parent.categories:
                        self.parent.categories.append(cat)
                        new_count += 1
                
                # Сохраняем обновленный список в R2
                self._save_categories_to_r2()
                self.update_categories_list()
                from app.gui.toast import show_toast
                show_toast(self.parent, f"Импортировано {new_count} новых категорий")
            except Exception as e:
                QMessageBox.critical(self.parent, "Ошибка", f"Ошибка импорта:\n{e}")

