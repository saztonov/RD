"""
Обрезка и сохранение блоков
Сохранение кропов блоков в виде изображений в структуру папок по категориям:
output/
  category1/
    src/
      page0_block{id}.jpg
    blocks.json
  category2/
    src/
    blocks.json
"""

import json
import logging
from pathlib import Path
from PIL import Image
from typing import List, Dict
from app.models import PageModel, Block, Document


logger = logging.getLogger(__name__)


def export_blocks_by_category(doc_path: str, pages: List[PageModel], base_output_dir: str) -> None:
    """
    Экспортировать кропы блоков, сгруппировав по категориям
    
    Args:
        doc_path: путь к исходному PDF
        pages: список PageModel со всеми страницами
        base_output_dir: базовая директория для выходных папок по категориям
    """
    try:
        base_output_path = Path(base_output_dir)
        base_output_path.mkdir(parents=True, exist_ok=True)
        
        # Группируем блоки по категориям
        blocks_by_category: Dict[str, List[Block]] = {}
        
        for page in pages:
            for block in page.blocks:
                if block.category not in blocks_by_category:
                    blocks_by_category[block.category] = []
                blocks_by_category[block.category].append(block)
        
        logger.info(f"Найдено категорий: {len(blocks_by_category)}")
        
        # Для каждой категории создаём папку и сохраняем блоки
        for category, blocks in blocks_by_category.items():
            category_dir = base_output_path / category
            src_dir = category_dir / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Обработка категории '{category}': {len(blocks)} блоков")
            
            # Сохраняем кропы и обновляем image_file
            for block in blocks:
                # Получаем изображение страницы
                if block.page_index >= len(pages):
                    logger.warning(f"Страница {block.page_index} для блока {block.id} не найдена")
                    continue
                
                page = pages[block.page_index]
                page_image = page.image
                
                # Обрезаем блок
                x1, y1, x2, y2 = block.coords_px
                crop = page_image.crop((x1, y1, x2, y2))
                
                # Сохраняем в JPEG
                crop_filename = f"page{block.page_index}_block{block.id}.jpg"
                crop_path = src_dir / crop_filename
                crop.save(crop_path, "JPEG", quality=95)
                
                # Обновляем путь в блоке (относительный путь от категории)
                block.image_file = f"src/{crop_filename}"
            
            # Сохраняем blocks.json для этой категории
            category_blocks_data = {
                "category": category,
                "original_pdf": doc_path,
                "blocks": []
            }
            
            for block in blocks:
                block_data = {
                    "id": block.id,
                    "page_index": block.page_index,
                    "coords_norm": list(block.coords_norm),
                    "block_type": block.block_type.value,
                    "category": block.category,
                    "image_file": block.image_file,
                    "source": block.source.value,
                    "ocr_text": block.ocr_text
                }
                category_blocks_data["blocks"].append(block_data)
            
            # Записываем JSON
            blocks_json_path = category_dir / "blocks.json"
            with open(blocks_json_path, 'w', encoding='utf-8') as f:
                json.dump(category_blocks_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Категория '{category}': {len(blocks)} кропов сохранено, blocks.json создан")
        
        total_blocks = sum(len(blocks) for blocks in blocks_by_category.values())
        logger.info(f"Экспорт завершён: {total_blocks} блоков в {len(blocks_by_category)} категориях")
    
    except Exception as e:
        logger.error(f"Ошибка экспорта блоков: {e}", exc_info=True)
        raise


class Cropper:
    """Legacy класс для совместимости с GUI (работа с Document)"""
    
    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: директория для сохранения кропов
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def save_block_crops(self, document: Document, page_images: Dict[int, Image.Image]) -> None:
        """
        Сохранить кропы всех блоков из Document
        
        Args:
            document: экземпляр Document
            page_images: словарь {page_number: PIL.Image}
        """
        try:
            for page in document.pages:
                page_num = page.page_number
                
                if page_num not in page_images:
                    logger.warning(f"Изображение для страницы {page_num} не найдено")
                    continue
                
                page_img = page_images[page_num]
                
                for block in page.blocks:
                    # Обрезаем блок
                    x1, y1, x2, y2 = block.coords_px
                    crop = page_img.crop((x1, y1, x2, y2))
                    
                    # Сохраняем
                    crop_filename = f"page{page_num}_block{block.id}.jpg"
                    crop_path = self.output_dir / crop_filename
                    crop.save(crop_path, "JPEG", quality=95)
                    
                    # Обновляем путь в блоке
                    block.image_file = crop_filename
            
            total_blocks = sum(len(page.blocks) for page in document.pages)
            logger.info(f"Сохранено {total_blocks} кропов в {self.output_dir}")
        
        except Exception as e:
            logger.error(f"Ошибка сохранения кропов: {e}")
            raise

