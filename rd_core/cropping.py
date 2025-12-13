"""Утилиты для вырезания кропов блоков из PDF страниц"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from PIL import Image

from rd_core.models import Block
from rd_core.pdf_utils import PDFDocument

logger = logging.getLogger(__name__)


def crop_block_from_image(
    page_image: Image.Image,
    block: Block,
    padding: int = 0
) -> Image.Image:
    """
    Вырезать кроп блока из изображения страницы
    
    Args:
        page_image: изображение страницы (PIL Image)
        block: блок с координатами
        padding: отступ вокруг блока в пикселях
    
    Returns:
        Вырезанное изображение блока
    """
    x1, y1, x2, y2 = block.coords_px
    
    # Добавляем padding
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(page_image.width, x2 + padding)
    y2 = min(page_image.height, y2 + padding)
    
    return page_image.crop((x1, y1, x2, y2))


def crop_blocks_from_pdf(
    pdf_path: str,
    blocks: List[Block],
    output_dir: str,
    padding: int = 5
) -> List[Tuple[Block, str]]:
    """
    Вырезать кропы всех блоков из PDF и сохранить в директорию
    
    Args:
        pdf_path: путь к PDF файлу
        blocks: список блоков для вырезания
        output_dir: директория для сохранения кропов
        padding: отступ вокруг блоков
    
    Returns:
        Список кортежей (block, crop_path)
    """
    os.makedirs(output_dir, exist_ok=True)
    results: List[Tuple[Block, str]] = []
    
    # Группируем блоки по страницам
    blocks_by_page: dict[int, List[Block]] = {}
    for block in blocks:
        page_idx = block.page_index
        if page_idx not in blocks_by_page:
            blocks_by_page[page_idx] = []
        blocks_by_page[page_idx].append(block)
    
    with PDFDocument(pdf_path) as pdf:
        for page_idx in sorted(blocks_by_page.keys()):
            page_blocks = blocks_by_page[page_idx]
            
            # Рендерим страницу
            page_image = pdf.render_page(page_idx)
            if page_image is None:
                logger.error(f"Не удалось отрендерить страницу {page_idx}")
                continue
            
            for block in page_blocks:
                try:
                    crop = crop_block_from_image(page_image, block, padding)
                    
                    # Формируем имя файла
                    crop_filename = f"block_{block.id}.png"
                    crop_path = os.path.join(output_dir, crop_filename)
                    
                    crop.save(crop_path, "PNG")
                    results.append((block, crop_path))
                    
                    logger.debug(f"Сохранён кроп блока {block.id}: {crop_path}")
                    
                except Exception as e:
                    logger.error(f"Ошибка при вырезании блока {block.id}: {e}")
    
    logger.info(f"Вырезано кропов: {len(results)}/{len(blocks)}")
    return results


def save_block_crop(
    block: Block,
    page_image: Image.Image,
    output_dir: str,
    padding: int = 5
) -> Optional[str]:
    """
    Сохранить кроп одного блока
    
    Args:
        block: блок для вырезания
        page_image: изображение страницы
        output_dir: директория для сохранения
        padding: отступ
    
    Returns:
        Путь к сохранённому файлу или None
    """
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        crop = crop_block_from_image(page_image, block, padding)
        
        crop_filename = f"block_{block.id}.png"
        crop_path = os.path.join(output_dir, crop_filename)
        
        crop.save(crop_path, "PNG")
        return crop_path
        
    except Exception as e:
        logger.error(f"Ошибка сохранения кропа {block.id}: {e}")
        return None
