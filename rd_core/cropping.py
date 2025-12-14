"""Утилиты для вырезания кропов блоков из PDF страниц"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field
from PIL import Image

from rd_core.models import Block, BlockType
from rd_core.pdf_utils import PDFDocument

logger = logging.getLogger(__name__)

MAX_STRIP_HEIGHT = 9000  # Максимальная высота объединённой полосы
MAX_SINGLE_BLOCK_HEIGHT = 9000  # Максимальная высота одиночного блока (разделяется если больше)


@dataclass
class MergedStrip:
    """Объединённая полоса блоков TEXT/TABLE"""
    blocks: List[Block] = field(default_factory=list)
    crops: List[Image.Image] = field(default_factory=list)
    total_height: int = 0
    max_width: int = 0
    strip_id: str = ""  # ID для сохранения файла


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


def split_large_crop(crop: Image.Image, max_height: int = MAX_SINGLE_BLOCK_HEIGHT, overlap: int = 100) -> List[Image.Image]:
    """
    Разделить большой кроп на части, если он превышает max_height.
    
    Args:
        crop: исходное изображение
        max_height: максимальная высота части
        overlap: перекрытие между частями для контекста
    
    Returns:
        Список частей изображения
    """
    if crop.height <= max_height:
        return [crop]
    
    parts = []
    y = 0
    part_height = max_height - overlap  # Эффективная высота с учётом перекрытия
    
    while y < crop.height:
        y_end = min(y + max_height, crop.height)
        part = crop.crop((0, y, crop.width, y_end))
        parts.append(part)
        
        y += part_height
        
        # Если осталось меньше overlap - завершаем
        if crop.height - y < overlap:
            break
    
    logger.info(f"Большой кроп {crop.height}px разделён на {len(parts)} частей")
    return parts


def merge_crops_vertically(crops: List[Image.Image], gap: int = 20) -> Image.Image:
    """
    Объединить кропы вертикально с разделителем.
    
    Args:
        crops: список изображений
        gap: отступ между блоками
    
    Returns:
        Объединённое изображение
    """
    if not crops:
        raise ValueError("Список кропов пуст")
    
    if len(crops) == 1:
        return crops[0]
    
    max_width = max(c.width for c in crops)
    total_height = sum(c.height for c in crops) + gap * (len(crops) - 1)
    
    # Создаём белый холст
    merged = Image.new('RGB', (max_width, total_height), (255, 255, 255))
    
    y_offset = 0
    for crop in crops:
        # Центрируем по горизонтали
        x_offset = (max_width - crop.width) // 2
        
        if crop.mode in ('RGBA', 'LA'):
            crop = crop.convert('RGB')
        
        merged.paste(crop, (x_offset, y_offset))
        y_offset += crop.height + gap
    
    return merged


def group_blocks_into_strips(
    blocks: List[Block],
    block_crops: Dict[str, Image.Image]
) -> Tuple[List[MergedStrip], List[Tuple[Block, Image.Image]]]:
    """
    Группировка TEXT/TABLE блоков в полосы до MAX_STRIP_HEIGHT px.
    IMAGE блоки возвращаются отдельно.
    Большие блоки (>9000px) разделяются на части.
    
    Args:
        blocks: список блоков отсортированный по порядку в документе
        block_crops: словарь block_id -> PIL Image
    
    Returns:
        (strips, image_blocks) - полосы TEXT/TABLE и отдельные IMAGE блоки
    """
    # Сортируем по странице и y-координате
    sorted_blocks = sorted(blocks, key=lambda b: (b.page_index, b.coords_px[1]))
    
    strips: List[MergedStrip] = []
    image_blocks: List[Tuple[Block, Image.Image]] = []
    
    current_strip = MergedStrip()
    strip_counter = 0
    
    for block in sorted_blocks:
        crop = block_crops.get(block.id)
        if not crop:
            continue
        
        if block.block_type == BlockType.IMAGE:
            # IMAGE блоки идут отдельно
            # Сначала закрываем текущую полосу если есть
            if current_strip.blocks:
                strip_counter += 1
                current_strip.strip_id = f"strip_{strip_counter:04d}"
                strips.append(current_strip)
                current_strip = MergedStrip()
            
            # Разделяем большие IMAGE блоки на части
            crop_parts = split_large_crop(crop, MAX_SINGLE_BLOCK_HEIGHT)
            for part in crop_parts:
                image_blocks.append((block, part))
            continue
        
        # TEXT или TABLE - разделяем если блок сам по себе больше 9000px
        crop_parts = split_large_crop(crop, MAX_SINGLE_BLOCK_HEIGHT)
        
        for crop_part in crop_parts:
            crop_height = crop_part.height
            crop_width = crop_part.width
            
            # Проверяем, влезет ли в текущую полосу
            if current_strip.total_height + crop_height > MAX_STRIP_HEIGHT and current_strip.blocks:
                # Закрываем текущую полосу, начинаем новую
                strip_counter += 1
                current_strip.strip_id = f"strip_{strip_counter:04d}"
                strips.append(current_strip)
                current_strip = MergedStrip()
            
            current_strip.blocks.append(block)
            current_strip.crops.append(crop_part)
            current_strip.total_height += crop_height + 20  # +gap
            current_strip.max_width = max(current_strip.max_width, crop_width)
    
    # Закрываем последнюю полосу
    if current_strip.blocks:
        strip_counter += 1
        current_strip.strip_id = f"strip_{strip_counter:04d}"
        strips.append(current_strip)
    
    logger.info(f"Сгруппировано: {len(strips)} полос TEXT/TABLE, {len(image_blocks)} IMAGE блоков")
    return strips, image_blocks


def crop_and_merge_blocks_from_pdf(
    pdf_path: str,
    blocks: List[Block],
    output_dir: str,
    padding: int = 5
) -> Tuple[Dict[str, str], Dict[str, Image.Image], List[MergedStrip], List[Tuple[Block, Image.Image]]]:
    """
    Вырезать кропы блоков из PDF, объединить TEXT/TABLE в полосы и сохранить.
    
    Args:
        pdf_path: путь к PDF файлу
        blocks: список блоков для вырезания
        output_dir: директория для сохранения кропов
        padding: отступ вокруг блоков
    
    Returns:
        (
            strip_paths: dict strip_id -> путь к файлу,
            strip_images: dict strip_id -> PIL Image,
            strips: список MergedStrip,
            image_blocks: список (block, crop) для IMAGE блоков
        )
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Сначала вырезаем все кропы отдельных блоков в память
    block_crops: Dict[str, Image.Image] = {}
    
    # Группируем блоки по страницам
    blocks_by_page: Dict[int, List[Block]] = {}
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
                    block_crops[block.id] = crop
                except Exception as e:
                    logger.error(f"Ошибка при вырезании блока {block.id}: {e}")
    
    # Группируем в полосы
    strips, image_blocks = group_blocks_into_strips(blocks, block_crops)
    
    strip_paths: Dict[str, str] = {}
    strip_images: Dict[str, Image.Image] = {}
    
    # Сохраняем объединённые кропы для полос TEXT/TABLE
    for strip in strips:
        if not strip.crops:
            continue
        
        try:
            merged_image = merge_crops_vertically(strip.crops)
            strip_images[strip.strip_id] = merged_image
            
            crop_filename = f"{strip.strip_id}.png"
            crop_path = os.path.join(output_dir, crop_filename)
            merged_image.save(crop_path, "PNG")
            strip_paths[strip.strip_id] = crop_path
            
            # Обновляем image_file у первого блока полосы (для ссылки)
            strip.blocks[0].image_file = crop_path
            
            logger.debug(f"Сохранена полоса {strip.strip_id}: {len(strip.blocks)} блоков, {merged_image.height}px")
        except Exception as e:
            logger.error(f"Ошибка сохранения полосы {strip.strip_id}: {e}")
    
    # Сохраняем кропы для IMAGE блоков отдельно
    for block, crop in image_blocks:
        try:
            crop_filename = f"image_{block.id}.png"
            crop_path = os.path.join(output_dir, crop_filename)
            crop.save(crop_path, "PNG")
            block.image_file = crop_path
            logger.debug(f"Сохранён IMAGE кроп {block.id}")
        except Exception as e:
            logger.error(f"Ошибка сохранения IMAGE кропа {block.id}: {e}")
    
    logger.info(f"Вырезано: {len(strip_paths)} полос, {len(image_blocks)} IMAGE блоков")
    return strip_paths, strip_images, strips, image_blocks
