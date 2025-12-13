"""
OCR обработка - все запросы идут на удалённый сервер
"""

import logging
from pathlib import Path
from typing import Protocol, List, Optional
from PIL import Image
from app.models import Block, BlockType

logger = logging.getLogger(__name__)


class OCRBackend(Protocol):
    """Интерфейс для OCR-движков"""
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None) -> str:
        """Распознать текст на изображении"""
        ...


class DummyOCRBackend:
    """Заглушка для OCR"""
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None) -> str:
        return "[OCR placeholder - OCR engine not configured]"


def generate_structured_markdown(pages: List, output_path: str, images_dir: str = "images", project_name: str = None) -> str:
    """
    Генерация markdown документа из размеченных блоков с учетом типов
    Блоки выводятся последовательно без разделения по страницам
    
    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения markdown файла
        images_dir: имя директории для изображений (относительно output_path)
        project_name: имя проекта для формирования ссылки на R2
    
    Returns:
        Путь к сохраненному файлу
    """
    try:
        from app.models import Page, BlockType
        import os
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Получаем публичный URL R2
        r2_public_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
        
        # Если project_name не указан, пытаемся получить из пути
        if not project_name:
            project_name = output_file.parent.name
        
        # Собираем все блоки со всех страниц
        all_blocks = []
        for page in pages:
            for block in page.blocks:
                all_blocks.append((page.page_number, block))
        
        # Сортируем: сначала по странице, затем по вертикальной позиции
        all_blocks.sort(key=lambda x: (x[0], x[1].coords_px[1]))
        
        markdown_parts = []
        
        for page_num, block in all_blocks:
            if not block.ocr_text:
                continue
            
            category_prefix = f"**{block.category}**\n\n" if block.category else ""
            
            if block.block_type == BlockType.IMAGE:
                # Для изображений: описание + ссылка на кроп в R2
                markdown_parts.append(f"{category_prefix}")
                markdown_parts.append(f"*Изображение:*\n\n")
                markdown_parts.append(f"{block.ocr_text}\n\n")
                
                # Добавляем ссылку на кроп в R2
                if block.image_file:
                    crop_filename = Path(block.image_file).name
                    r2_url = f"{r2_public_url}/ocr_results/{project_name}/crops/{crop_filename}"
                    markdown_parts.append(f"![Изображение]({r2_url})\n\n")
            
            elif block.block_type == BlockType.TABLE:
                markdown_parts.append(f"{category_prefix}")
                markdown_parts.append(f"{block.ocr_text}\n\n")
                
            elif block.block_type == BlockType.TEXT:
                markdown_parts.append(f"{category_prefix}")
                markdown_parts.append(f"{block.ocr_text}\n\n")
        
        # Объединяем и сохраняем
        full_markdown = "".join(markdown_parts)
        output_file.write_text(full_markdown, encoding='utf-8')
        
        logger.info(f"Структурированный markdown документ сохранен: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка генерации структурированного markdown: {e}", exc_info=True)
        raise
