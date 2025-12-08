"""
Менеджер промтов для типов блоков и категорий
Все промты хранятся ТОЛЬКО в R2 Storage (rd1/prompts/)
"""

import logging
from typing import Optional
from PySide6.QtWidgets import QMessageBox, QDialog
from app.r2_storage import R2Storage
from app.gui.prompt_editor_dialog import PromptEditorDialog

logger = logging.getLogger(__name__)


class PromptManager:
    """Управление промтами для OCR - все данные из R2"""
    
    PROMPTS_PREFIX = "prompts"
    
    # Базовые типы блоков (промпты для них должны быть в R2)
    BLOCK_TYPES = ["text", "table", "image"]
    
    def __init__(self, parent):
        self.parent = parent
        self.r2_storage: Optional[R2Storage] = None
        self._init_r2()
    
    def _init_r2(self):
        """Инициализация R2 Storage"""
        try:
            self.r2_storage = R2Storage()
            logger.info("✅ PromptManager: R2Storage инициализирован")
        except Exception as e:
            logger.warning(f"⚠️ R2Storage недоступен: {e}")
            self.r2_storage = None
    
    def get_prompt_key(self, name: str) -> str:
        """Получить ключ для промта в R2"""
        return f"{self.PROMPTS_PREFIX}/{name}.txt"
    
    def load_prompt(self, name: str) -> Optional[str]:
        """
        Загрузить промт из R2
        
        Args:
            name: Имя промта (например 'text', 'table', 'image' или 'category_XXX')
        
        Returns:
            Текст промта или None
        """
        if not self.r2_storage:
            logger.warning("R2 недоступен, промт не загружен")
            return None
        
        key = self.get_prompt_key(name)
        return self.r2_storage.download_text(key)
    
    def save_prompt(self, name: str, content: str) -> bool:
        """
        Сохранить промт в R2
        
        Args:
            name: Имя промта
            content: Текст промта
        
        Returns:
            True если успешно
        """
        if not self.r2_storage:
            QMessageBox.warning(
                self.parent,
                "R2 недоступен",
                "R2 Storage не настроен. Проверьте .env файл."
            )
            return False
        
        key = self.get_prompt_key(name)
        result = self.r2_storage.upload_text(content, key)
        
        if result:
            logger.info(f"✅ Промт сохранен в R2: {name}")
        else:
            logger.error(f"❌ Ошибка сохранения промта: {name}")
        
        return result
    
    def edit_prompt(self, name: str, title: str, default_content: str = "") -> bool:
        """
        Открыть диалог редактирования промта из R2
        
        Args:
            name: Имя промта для сохранения (ключ в R2)
            title: Заголовок диалога
            default_content: Содержимое по умолчанию (если в R2 пусто)
        
        Returns:
            True если промт был изменен и сохранен
        """
        # Загружаем существующий промт из R2
        current_prompt = self.load_prompt(name)
        
        if current_prompt is None:
            current_prompt = default_content or f"Промт для '{name}' не найден в R2.\nСоздайте новый промт здесь."
        
        # Открываем диалог с указанием ключа R2
        dialog = PromptEditorDialog(self.parent, title, current_prompt, prompt_key=name)
        if dialog.exec() == QDialog.Accepted:
            new_prompt = dialog.get_prompt_text()
            
            # Сохраняем в R2
            if self.save_prompt(name, new_prompt):
                QMessageBox.information(
                    self.parent,
                    "Успех",
                    f"Промт сохранен в R2:\nrd1/prompts/{name}.txt"
                )
                return True
        
        return False
    
    def ensure_default_prompts(self):
        """Проверить что базовые промты существуют в R2"""
        if not self.r2_storage:
            logger.warning("⚠️ R2 недоступен, проверка промптов пропущена")
            return
        
        missing_prompts = []
        for name in self.BLOCK_TYPES:
            if not self.load_prompt(name):
                missing_prompts.append(name)
        
        if missing_prompts:
            logger.warning(f"⚠️ Отсутствуют промпты в R2 (rd1/prompts/): {missing_prompts}")
            logger.warning(f"⚠️ Загрузите промпты в R2 через scripts/upload_prompts_to_r2.py")
    
    def ensure_standard_categories(self) -> list[str]:
        """Загрузить категории из R2 (не из кода!)"""
        return self.load_categories_from_r2()
    
    def load_categories_from_r2(self) -> list[str]:
        """
        Загрузить список категорий из R2
        
        Returns:
            Список названий категорий (пустой если R2 недоступен)
        """
        if not self.r2_storage:
            logger.warning("R2 недоступен, категории не загружены")
            return []
        
        # Загружаем список категорий из специального файла
        categories_key = "prompts/categories_list.txt"
        content = self.r2_storage.download_text(categories_key)
        
        if content:
            categories = [line.strip() for line in content.split('\n') if line.strip()]
            logger.info(f"✅ Загружено {len(categories)} категорий из R2")
            return categories
        
        logger.info("⚠️ Список категорий не найден в R2 (rd1/prompts/categories_list.txt)")
        return []
    
    def save_categories_to_r2(self, categories: list[str]) -> bool:
        """
        Сохранить список категорий в R2
        
        Args:
            categories: Список категорий
        
        Returns:
            True если успешно
        """
        if not self.r2_storage:
            return False
        
        categories_key = "prompts/categories_list.txt"
        content = '\n'.join(categories)
        
        result = self.r2_storage.upload_text(content, categories_key)
        if result:
            logger.info(f"✅ Сохранено {len(categories)} категорий в R2")
        return result
    
    def get_category_prompt_name(self, category: str) -> str:
        """Получить имя промпта для категории"""
        return f"category_{category}"
    
    def delete_prompt(self, name: str) -> bool:
        """
        Удалить промт из R2
        
        Args:
            name: Имя промпта
        
        Returns:
            True если успешно
        """
        if not self.r2_storage:
            return False
        
        key = self.get_prompt_key(name)
        result = self.r2_storage.delete_object(key)
        
        if result:
            logger.info(f"✅ Промт удален из R2: {name}")
        else:
            logger.error(f"❌ Ошибка удаления промта: {name}")
        
        return result
    
    def list_prompts_from_r2(self) -> list[str]:
        """
        Получить список всех промптов из R2
        
        Returns:
            Список имен промптов
        """
        if not self.r2_storage:
            return []
        
        keys = self.r2_storage.list_by_prefix(self.PROMPTS_PREFIX + "/")
        prompts = []
        for key in keys:
            if key.endswith('.txt') and key != "prompts/categories_list.txt":
                # Извлекаем имя промта из ключа
                name = key.replace(self.PROMPTS_PREFIX + "/", "").replace(".txt", "")
                prompts.append(name)
        
        return prompts

