"""
Менеджер промтов для типов блоков и категорий
Хранит промты в R2 Storage
"""

import logging
from typing import Optional
from PySide6.QtWidgets import QMessageBox, QDialog
from app.r2_storage import R2Storage
from app.gui.prompt_editor_dialog import PromptEditorDialog

logger = logging.getLogger(__name__)


class PromptManager:
    """Управление промтами для OCR"""
    
    PROMPTS_PREFIX = "prompts"
    
    # Стандартные категории с промптами
    STANDARD_CATEGORIES = {
        "Текст": "text",
        "Таблица": "table",
        "Картинка": "image"
    }
    
    DEFAULT_PROMPTS = {
        "text": "Распознай текст на изображении. Сохрани форматирование и структуру.",
        "table": "Распознай таблицу на изображении. Преобразуй в markdown формат с колонками и строками.",
        "image": "Опиши содержимое изображения. Укажи все важные детали, объекты и текст если есть."
    }
    
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
            name: Имя промта (например 'text', 'table', 'image' или название категории)
        
        Returns:
            Текст промта или None
        """
        if not self.r2_storage:
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
            logger.info(f"✅ Промт сохранен: {name}")
        else:
            logger.error(f"❌ Ошибка сохранения промта: {name}")
        
        return result
    
    def edit_prompt(self, name: str, title: str, default_content: str = "") -> bool:
        """
        Открыть диалог редактирования промта
        
        Args:
            name: Имя промта для сохранения
            title: Заголовок диалога
            default_content: Содержимое по умолчанию
        
        Returns:
            True если промт был изменен и сохранен
        """
        # Загружаем существующий промт или используем дефолтный
        current_prompt = self.load_prompt(name) or default_content
        
        # Открываем диалог
        dialog = PromptEditorDialog(self.parent, title, current_prompt)
        if dialog.exec() == QDialog.Accepted:
            new_prompt = dialog.get_prompt_text()
            
            # Сохраняем в R2
            if self.save_prompt(name, new_prompt):
                QMessageBox.information(
                    self.parent,
                    "Успех",
                    f"Промт '{name}' сохранен в R2"
                )
                return True
        
        return False
    
    def _load_local_prompt(self, filename: str) -> Optional[str]:
        """Загрузить промт из локального файла prompts/"""
        from pathlib import Path
        try:
            prompt_path = Path(__file__).parent.parent.parent / "prompts" / filename
            if prompt_path.exists():
                return prompt_path.read_text(encoding='utf-8').strip()
        except Exception as e:
            logger.warning(f"⚠️ Не удалось загрузить локальный промт {filename}: {e}")
        return None
    
    def ensure_default_prompts(self, force_reload: bool = False):
        """
        Убедиться что базовые промты существуют
        
        Args:
            force_reload: Принудительно перезагрузить из локальных файлов
        """
        if not self.r2_storage:
            return
        
        # Загружаем промты типов блоков из локальных файлов
        for name in self.DEFAULT_PROMPTS.keys():
            # Проверяем существующий промт
            existing = self.load_prompt(name)
            
            # Загружаем из локального файла
            local_prompt = self._load_local_prompt(f"{name}.txt")
            
            if local_prompt:
                # Если есть локальный файл - используем его (при force_reload или отсутствии в R2)
                if force_reload or existing is None:
                    self.save_prompt(name, local_prompt)
                    logger.info(f"✅ Загружен промт {name} из локального файла в R2")
            elif existing is None:
                # Если нет ни локального, ни в R2 - используем дефолтный
                content = self.DEFAULT_PROMPTS[name]
                self.save_prompt(name, content)
                logger.info(f"✅ Создан дефолтный промт: {name}")
    
    def ensure_standard_categories(self) -> list[str]:
        """
        Убедиться что стандартные категории существуют
        
        Returns:
            Список стандартных категорий
        """
        if not self.r2_storage:
            return list(self.STANDARD_CATEGORIES.keys())
        
        standard_cats = []
        
        for category_name, prompt_type in self.STANDARD_CATEGORIES.items():
            standard_cats.append(category_name)
            
            # Проверяем промт категории
            prompt_name = self.get_category_prompt_name(category_name)
            existing = self.load_prompt(prompt_name)
            
            if existing is None:
                # Загружаем промт из локального файла или используем дефолтный
                local_prompt = self._load_local_prompt(f"{prompt_type}.txt")
                content = local_prompt or self.DEFAULT_PROMPTS.get(prompt_type, "")
                
                if content:
                    self.save_prompt(prompt_name, content)
                    logger.info(f"✅ Создан промт для стандартной категории: {category_name}")
        
        return standard_cats
    
    def load_categories_from_r2(self) -> list[str]:
        """
        Загрузить список категорий из R2
        
        Returns:
            Список названий категорий
        """
        if not self.r2_storage:
            return list(self.STANDARD_CATEGORIES.keys())
        
        # Загружаем список категорий из специального файла
        categories_key = "prompts/categories_list.txt"
        content = self.r2_storage.download_text(categories_key)
        
        if content:
            categories = [line.strip() for line in content.split('\n') if line.strip()]
            logger.info(f"✅ Загружено {len(categories)} категорий из R2")
            return categories
        
        # Если список не найден - создаем стандартные категории
        logger.info("⚠️ Список категорий не найден в R2, создаем стандартные")
        standard_cats = self.ensure_standard_categories()
        
        # Сохраняем стандартные категории в R2
        if standard_cats:
            self.save_categories_to_r2(standard_cats)
        
        return standard_cats
    
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
            logger.info(f"✅ Промт удален: {name}")
        else:
            logger.error(f"❌ Ошибка удаления промта: {name}")
        
        return result

