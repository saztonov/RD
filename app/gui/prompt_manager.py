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
    
    DEFAULT_PROMPTS = {
        "text": "Распознай текст на изображении. Сохрани форматирование и структуру.",
        "table": "Распознай таблицу на изображении. Преобразуй в markdown формат с колонками и строками.",
        "image": "Опиши содержимое изображения. Укажи все важные детали, объекты и текст если есть."
    }
    
    def __init__(self, parent):
        self.parent = parent
        self.r2_storage: Optional[R2Storage] = None
        # self._init_r2()  # Отключено тестирование R2 при запуске
    
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
    
    def ensure_default_prompts(self):
        """Убедиться что базовые промты существуют"""
        if not self.r2_storage:
            return
        
        for name, content in self.DEFAULT_PROMPTS.items():
            existing = self.load_prompt(name)
            if existing is None:
                self.save_prompt(name, content)
                logger.info(f"✅ Создан дефолтный промт: {name}")

