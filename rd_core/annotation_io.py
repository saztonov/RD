"""
Сохранение и загрузка разметки
Работа с JSON-файлами для сохранения/загрузки annotations.json
"""

import json
import logging
from typing import Optional
from rd_core.models import Document


logger = logging.getLogger(__name__)


class AnnotationIO:
    """Legacy класс для совместимости с GUI (работа с Document)"""
    
    @staticmethod
    def save_annotation(document: Document, file_path: str) -> None:
        """
        Сохранить разметку Document в JSON
        
        Args:
            document: экземпляр Document
            file_path: путь к выходному JSON-файлу
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(document.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"Разметка сохранена: {file_path}")
        except Exception as e:
            logger.error(f"Ошибка сохранения разметки: {e}")
            raise
    
    @staticmethod
    def load_annotation(file_path: str, migrate_ids: bool = True) -> tuple[Optional[Document], bool]:
        """
        Загрузить разметку Document из JSON
        
        Args:
            file_path: путь к JSON-файлу
            migrate_ids: мигрировать legacy UUID в armor ID формат
        
        Returns:
            (Document, was_migrated) - документ и флаг миграции ID
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            doc, was_migrated = Document.from_dict(data, migrate_ids)
            logger.info(f"Разметка загружена: {file_path}" + 
                       (" (ID мигрированы)" if was_migrated else ""))
            return doc, was_migrated
        except Exception as e:
            logger.error(f"Ошибка загрузки разметки: {e}")
            return None, False

