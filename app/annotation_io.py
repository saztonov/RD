"""
Сохранение и загрузка разметки
Работа с JSON-файлами для сохранения/загрузки blocks.json
"""

import json
import logging
from pathlib import Path
from typing import Optional
from app.models import Document


logger = logging.getLogger(__name__)


class AnnotationIO:
    """
    Класс для сохранения и загрузки разметки в JSON
    """
    
    @staticmethod
    def save_annotation(document: Document, output_path: str) -> bool:
        """
        Сохранить разметку в JSON-файл
        
        Args:
            document: документ с разметкой
            output_path: путь к JSON-файлу (обычно blocks.json)
        
        Returns:
            True если успешно сохранено
        """
        try:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Подсчёт блоков
            total_blocks = sum(len(page.blocks) for page in document.pages)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(document.to_dict(), f, ensure_ascii=False, indent=2)
            
            logger.info(f"Разметка сохранена: {output_path} (страниц: {len(document.pages)}, блоков: {total_blocks})")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения разметки в {output_path}: {e}")
            return False
    
    @staticmethod
    def load_annotation(input_path: str) -> Optional[Document]:
        """
        Загрузить разметку из JSON-файла
        
        Args:
            input_path: путь к JSON-файлу
        
        Returns:
            Document или None в случае ошибки
        """
        try:
            input_file = Path(input_path)
            
            if not input_file.exists():
                logger.error(f"Файл разметки не найден: {input_path}")
                return None
            
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            document = Document.from_dict(data)
            
            total_blocks = sum(len(page.blocks) for page in document.pages)
            logger.info(f"Разметка загружена: {input_path} (страниц: {len(document.pages)}, блоков: {total_blocks})")
            
            return document
        except json.JSONDecodeError as e:
            logger.error(f"Некорректный JSON в файле {input_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка загрузки разметки из {input_path}: {e}")
            return None

