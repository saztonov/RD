"""
Менеджер промтов для типов блоков
Все промты хранятся ТОЛЬКО в R2 Storage (rd1/prompts/) в JSON формате
Формат: {"system": "...", "user": "..."}
"""

import json
import logging
from typing import Optional
from PySide6.QtWidgets import QMessageBox, QDialog
from rd_core.r2_storage import R2Storage
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
        """Получить ключ для промта в R2 (JSON формат)"""
        return f"{self.PROMPTS_PREFIX}/{name}.json"
    
    def load_prompt(self, name: str) -> Optional[dict]:
        """
        Загрузить промт из R2
        
        Args:
            name: Имя промта (например 'text', 'table', 'image')
        
        Returns:
            Dict с ключами 'system' и 'user' или None
        """
        if not self.r2_storage:
            logger.warning("R2 недоступен, промт не загружен")
            return None
        
        key = self.get_prompt_key(name)
        content = self.r2_storage.download_text(key)
        
        if content:
            try:
                data = json.loads(content)
                return {
                    "system": data.get("system", ""),
                    "user": data.get("user", "")
                }
            except json.JSONDecodeError:
                # Старый формат - простой текст, конвертируем
                logger.info(f"Конвертация старого формата промта: {name}")
                return {"system": "", "user": content}
        
        # Пробуем загрузить старый .txt формат для миграции
        old_key = f"{self.PROMPTS_PREFIX}/{name}.txt"
        old_content = self.r2_storage.download_text(old_key)
        if old_content:
            logger.info(f"Миграция промта из .txt: {name}")
            return {"system": "", "user": old_content}
        
        return None
    
    def save_prompt(self, name: str, content: dict) -> bool:
        """
        Сохранить промт в R2
        
        Args:
            name: Имя промта
            content: Dict с ключами 'system' и 'user'
        
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
        json_content = json.dumps(content, ensure_ascii=False, indent=2)
        result = self.r2_storage.upload_text(json_content, key)
        
        if result:
            logger.info(f"✅ Промт сохранен в R2: {name}")
        else:
            logger.error(f"❌ Ошибка сохранения промта: {name}")
        
        return result
    
    def edit_prompt(self, name: str, title: str, default_content: dict = None) -> bool:
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
            current_prompt = default_content or {
                "system": "You are an expert assistant for document analysis.",
                "user": f"Analyze the provided image of '{name}' block."
            }
        
        # Открываем диалог с указанием ключа R2
        dialog = PromptEditorDialog(self.parent, title, current_prompt, prompt_key=name)
        if dialog.exec() == QDialog.Accepted:
            new_prompt = dialog.get_prompt_data()
            
            # Сохраняем в R2
            if self.save_prompt(name, new_prompt):
                QMessageBox.information(
                    self.parent,
                    "Успех",
                    f"Промт сохранен в R2:\nrd1/prompts/{name}.json"
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
            logger.warning(f"⚠️ Загрузите промпты в R2 или создайте через UI")
    
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
            if key.endswith('.json'):
                # Извлекаем имя промта из ключа
                name = key.replace(self.PROMPTS_PREFIX + "/", "").replace(".json", "")
                prompts.append(name)
        
        return prompts
    
    def list_prompts_with_metadata(self) -> list[dict]:
        """
        Получить список всех промптов из R2 с метаданными
        
        Returns:
            Список dict: {name, last_modified}
        """
        if not self.r2_storage:
            return []
        
        objects = self.r2_storage.list_objects_with_metadata(self.PROMPTS_PREFIX + "/")
        prompts = []
        
        for obj in objects:
            key = obj['Key']
            if key.endswith('.json'):
                name = key.replace(self.PROMPTS_PREFIX + "/", "").replace(".json", "")
                prompts.append({
                    'name': name,
                    'last_modified': obj.get('LastModified'),
                })
        
        return prompts

