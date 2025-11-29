"""
Сохранение и загрузка разметки
Работа с JSON-файлами для сохранения/загрузки annotations.json
"""

import json
import logging
from pathlib import Path
from typing import List, Optional
from PIL import Image
from app.models import PageModel, Block, Document


logger = logging.getLogger(__name__)


def save_annotations(doc_path: str, pages: List[PageModel], output_dir: str) -> None:
    """
    Сохранить разметку в общий annotations.json
    
    Args:
        doc_path: путь к исходному PDF
        pages: список PageModel со всеми страницами
        output_dir: директория для выходных файлов
    """
    try:
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем информацию о документе и блоках
        annotations_data = {
            "pdf_path": doc_path,
            "pages": []
        }
        
        # Для каждой страницы сохраняем метаданные (без самих изображений)
        for page in pages:
            page_data = {
                "page_index": page.page_index,
                "width": page.width,
                "height": page.height,
                "blocks": [block.to_dict() for block in page.blocks]
            }
            annotations_data["pages"].append(page_data)
        
        # Записываем в JSON
        output_json_path = output_dir_path / "annotations.json"
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(annotations_data, f, ensure_ascii=False, indent=2)
        
        total_blocks = sum(len(page.blocks) for page in pages)
        logger.info(f"Разметка сохранена: {output_json_path} (страниц: {len(pages)}, блоков: {total_blocks})")
    
    except Exception as e:
        logger.error(f"Ошибка сохранения разметки: {e}")
        raise


def load_annotations(json_path: str, images: List[Image.Image]) -> List[PageModel]:
    """
    Загрузить разметку из annotations.json и привязать к изображениям
    
    Args:
        json_path: путь к JSON-файлу
        images: список PIL.Image для каждой страницы (в порядке page_index)
    
    Returns:
        Список PageModel с восстановленными блоками
    """
    try:
        json_file = Path(json_path)
        
        if not json_file.exists():
            logger.error(f"Файл разметки не найден: {json_path}")
            return []
        
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        pages = []
        
        for page_data in data.get("pages", []):
            # Поддержка page_number из legacy модели
            page_index = page_data.get("page_index")
            if page_index is None:
                page_index = page_data.get("page_number")
                
            if page_index is None:
                logger.warning(f"Страница без индекса, пропускаем: {page_data.keys()}")
                continue
            
            # Проверяем наличие соответствующего изображения
            if page_index >= len(images):
                logger.warning(f"Изображение для страницы {page_index} не найдено, пропускаем")
                continue
            
            image = images[page_index]
            
            # Создаём PageModel
            page_model = PageModel(
                page_index=page_index,
                image=image,
                blocks=[]
            )
            
            # Восстанавливаем блоки
            for block_data in page_data.get("blocks", []):
                block = Block.from_dict(block_data)
                
                # Пересчитываем пиксельные координаты по текущему размеру изображения
                stored_width = page_data.get("width", image.width)
                stored_height = page_data.get("height", image.height)
                
                if stored_width != image.width or stored_height != image.height:
                    # Пересчитываем координаты из нормализованных
                    block.coords_px = Block.norm_to_px(
                        block.coords_norm,
                        image.width,
                        image.height
                    )
                
                page_model.add_block(block)
            
            pages.append(page_model)
        
        total_blocks = sum(len(page.blocks) for page in pages)
        logger.info(f"Разметка загружена: {json_path} (страниц: {len(pages)}, блоков: {total_blocks})")
        
        return pages
    
    except json.JSONDecodeError as e:
        logger.error(f"Некорректный JSON в файле {json_path}: {e}")
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки разметки: {e}")
        return []


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
    def load_annotation(file_path: str) -> Optional[Document]:
        """
        Загрузить разметку Document из JSON
        
        Args:
            file_path: путь к JSON-файлу
        
        Returns:
            Экземпляр Document или None при ошибке
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            doc = Document.from_dict(data)
            logger.info(f"Разметка загружена: {file_path}")
            return doc
        except Exception as e:
            logger.error(f"Ошибка загрузки разметки: {e}")
            return None

