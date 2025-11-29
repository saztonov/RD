"""
Обрезка и сохранение блоков
Сохранение кропов блоков в виде изображений в структуру папок:
output/
  text/
    src/
      page_1_block_1.png
  table/
    src/
  image/
    src/
"""

import logging
from pathlib import Path
from PIL import Image
from typing import List
from app.models import Document, Block, BlockType


logger = logging.getLogger(__name__)


class Cropper:
    """
    Класс для обрезки и сохранения блоков из PDF-страниц
    """
    
    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: базовая директория для сохранения кропов
        """
        self.output_dir = Path(output_dir)
    
    def save_block_crops(self, document: Document, page_images: dict) -> bool:
        """
        Сохранить все блоки документа в виде изображений
        
        Args:
            document: документ с разметкой
            page_images: словарь {page_number: PIL.Image} - отрендеренные страницы
        
        Returns:
            True если успешно сохранено
        """
        try:
            # Создаём структуру папок
            logger.info(f"Создание структуры папок в: {self.output_dir}")
            for block_type in BlockType:
                type_dir = self.output_dir / block_type.value / "src"
                type_dir.mkdir(parents=True, exist_ok=True)
            
            # Подсчёт блоков
            total_blocks = sum(len(page.blocks) for page in document.pages)
            saved_count = 0
            
            # Обрезаем и сохраняем каждый блок
            for page in document.pages:
                page_num = page.page_number
                if page_num not in page_images:
                    logger.warning(f"Страница {page_num} не найдена в кеше изображений, пропускаем")
                    continue
                
                page_image = page_images[page_num]
                
                for idx, block in enumerate(page.blocks):
                    crop_image = self._crop_block(page_image, block)
                    if crop_image:
                        filename = f"page_{page_num + 1}_block_{idx + 1}.png"
                        save_path = self.output_dir / block.block_type.value / "src" / filename
                        crop_image.save(save_path)
                        saved_count += 1
                        
                        if saved_count % 10 == 0:
                            logger.info(f"Сохранено блоков: {saved_count}/{total_blocks}")
            
            logger.info(f"Экспорт кропов завершён: {saved_count}/{total_blocks} блоков сохранено в {self.output_dir}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения кропов: {e}", exc_info=True)
            return False
    
    def _crop_block(self, page_image: Image.Image, block: Block) -> Image.Image:
        """
        Обрезать блок из изображения страницы
        
        Args:
            page_image: изображение страницы
            block: блок с координатами
        
        Returns:
            Обрезанное изображение
        """
        # Координаты для PIL: (left, top, right, bottom)
        box = (
            block.x,
            block.y,
            block.x + block.width,
            block.y + block.height
        )
        return page_image.crop(box)

