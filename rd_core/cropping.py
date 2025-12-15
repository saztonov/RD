"""Утилиты для вырезания кропов блоков из PDF страниц"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field
from PIL import Image
import fitz  # PyMuPDF

from rd_core.models import Block, BlockType, ShapeType
from rd_core.pdf_utils import PDFDocument, PDF_RENDER_ZOOM
from PIL import ImageDraw

logger = logging.getLogger(__name__)

MAX_STRIP_HEIGHT = 9000  # Максимальная высота объединённой полосы
MAX_SINGLE_BLOCK_HEIGHT = 9000  # Максимальная высота одиночного блока (разделяется если больше)


@dataclass
class BlockPart:
    """Часть блока (для блоков >9000px)"""
    block: Block
    crop: Image.Image
    part_idx: int  # Индекс части (0, 1, 2, ...)
    total_parts: int  # Общее число частей


@dataclass
class MergedStrip:
    """Объединённая полоса блоков TEXT/TABLE"""
    blocks: List[Block] = field(default_factory=list)
    crops: List[Image.Image] = field(default_factory=list)
    block_parts: List[BlockPart] = field(default_factory=list)  # Метаинфо о частях
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
    
    # Для прямоугольников - простой crop
    if block.shape_type == ShapeType.RECTANGLE or not block.polygon_points:
        return page_image.crop((x1, y1, x2, y2))
    
    # Для полигонов - используем маску
    # Создаём маску размером с bounding box
    mask = Image.new('L', (x2 - x1, y2 - y1), 0)
    draw = ImageDraw.Draw(mask)
    
    # Смещаем координаты полигона относительно bounding box
    adjusted_points = [(x - x1, y - y1) for x, y in block.polygon_points]
    
    # Рисуем полигон на маске
    draw.polygon(adjusted_points, fill=255)
    
    # Вырезаем прямоугольную область
    cropped = page_image.crop((x1, y1, x2, y2))
    
    # Создаём белый фон
    result = Image.new('RGB', cropped.size, (255, 255, 255))
    
    # Накладываем вырезанную область через маску
    result.paste(cropped, mask=mask)
    
    return result


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


def crop_block_to_pdf(
    pdf_doc: fitz.Document,
    block: Block,
    output_path: str,
    padding: int = 5,
    page_image: Optional[Image.Image] = None
) -> Optional[str]:
    """
    Вырезать блок из PDF и сохранить как отдельный PDF.
    Для прямоугольников - векторный формат.
    Для полигонов - растровый с маской (белый фон снаружи).
    
    Args:
        pdf_doc: открытый PyMuPDF документ
        block: блок с координатами (coords_px в пикселях при zoom)
        output_path: путь для сохранения PDF
        padding: отступ в пикселях (при zoom)
        page_image: изображение страницы (нужно для полигонов)
    
    Returns:
        Путь к сохранённому PDF или None
    """
    try:
        # Для полигонов - векторный PDF с белой маской снаружи
        if block.shape_type == ShapeType.POLYGON and block.polygon_points:
            page = pdf_doc[block.page_index]
            
            # Координаты bounding box в PDF points
            x1, y1, x2, y2 = block.coords_px
            x1_pt = (x1 - padding) / PDF_RENDER_ZOOM
            y1_pt = (y1 - padding) / PDF_RENDER_ZOOM
            x2_pt = (x2 + padding) / PDF_RENDER_ZOOM
            y2_pt = (y2 + padding) / PDF_RENDER_ZOOM
            
            # Ограничиваем границами страницы
            rect = page.rect
            x1_pt = max(0, x1_pt)
            y1_pt = max(0, y1_pt)
            x2_pt = min(rect.width, x2_pt)
            y2_pt = min(rect.height, y2_pt)
            
            clip_rect = fitz.Rect(x1_pt, y1_pt, x2_pt, y2_pt)
            
            # Создаём новый PDF
            new_doc = fitz.open()
            new_page = new_doc.new_page(width=clip_rect.width, height=clip_rect.height)
            
            # Копируем векторное содержимое (прямоугольный clip)
            new_page.show_pdf_page(new_page.rect, pdf_doc, block.page_index, clip=clip_rect)
            
            # Конвертируем polygon_points в PDF points относительно новой страницы
            polygon_pts = []
            for px, py in block.polygon_points:
                pt_x = (px / PDF_RENDER_ZOOM) - x1_pt
                pt_y = (py / PDF_RENDER_ZOOM) - y1_pt
                polygon_pts.append(fitz.Point(pt_x, pt_y))
            
            # Рисуем белую маску СНАРУЖИ полигона
            # Создаём путь: прямоугольник страницы с вырезанным полигоном внутри
            shape = new_page.new_shape()
            
            # Внешний прямоугольник (вся страница)
            shape.draw_rect(new_page.rect)
            
            # Внутренний полигон (вырезаем)
            if polygon_pts:
                shape.draw_polyline(polygon_pts + [polygon_pts[0]])  # замыкаем
            
            # Заливаем белым с правилом even-odd (снаружи полигона)
            shape.finish(color=None, fill=(1, 1, 1), even_odd=True)
            shape.commit()
            
            new_doc.save(output_path, deflate=True, garbage=4)
            new_doc.close()
            
            logger.debug(f"Сохранён векторный PDF-кроп полигона {block.id}: {output_path}")
            return output_path
        
        # Для прямоугольников - векторный формат
        page = pdf_doc[block.page_index]
        
        # Конвертируем coords_px (пиксели при zoom) обратно в PDF points
        x1, y1, x2, y2 = block.coords_px
        # PDF_RENDER_ZOOM = 300/72 ≈ 4.167
        x1_pt = (x1 - padding) / PDF_RENDER_ZOOM
        y1_pt = (y1 - padding) / PDF_RENDER_ZOOM
        x2_pt = (x2 + padding) / PDF_RENDER_ZOOM
        y2_pt = (y2 + padding) / PDF_RENDER_ZOOM
        
        # Ограничиваем границами страницы
        rect = page.rect
        x1_pt = max(0, x1_pt)
        y1_pt = max(0, y1_pt)
        x2_pt = min(rect.width, x2_pt)
        y2_pt = min(rect.height, y2_pt)
        
        clip_rect = fitz.Rect(x1_pt, y1_pt, x2_pt, y2_pt)
        
        # Создаём новый PDF с одной страницей
        new_doc = fitz.open()
        new_page = new_doc.new_page(width=clip_rect.width, height=clip_rect.height)
        
        # Копируем содержимое области в новую страницу
        new_page.show_pdf_page(new_page.rect, pdf_doc, block.page_index, clip=clip_rect)
        
        # Сохраняем
        new_doc.save(output_path)
        new_doc.close()
        
        logger.debug(f"Сохранён PDF-кроп блока {block.id}: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Ошибка создания PDF-кропа {block.id}: {e}")
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
) -> Tuple[List[MergedStrip], List[Tuple[Block, Image.Image, int, int]]]:
    """
    Группировка TEXT/TABLE блоков в полосы до MAX_STRIP_HEIGHT px.
    IMAGE блоки возвращаются отдельно.
    Большие блоки (>9000px) разделяются на части.
    
    Args:
        blocks: список блоков отсортированный по порядку в документе
        block_crops: словарь block_id -> PIL Image
    
    Returns:
        (strips, image_blocks) - полосы TEXT/TABLE и IMAGE блоки с метаинфо (block, crop, part_idx, total_parts)
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
            for part_idx, part in enumerate(crop_parts):
                # Добавляем индекс части для объединения результатов
                image_blocks.append((block, part, part_idx, len(crop_parts)))
            continue
        
        # TEXT или TABLE - разделяем если блок сам по себе больше 9000px
        crop_parts = split_large_crop(crop, MAX_SINGLE_BLOCK_HEIGHT)
        total_parts = len(crop_parts)
        
        for part_idx, crop_part in enumerate(crop_parts):
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
            current_strip.block_parts.append(BlockPart(block, crop_part, part_idx, total_parts))
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
    padding: int = 5,
    save_image_crops_as_pdf: bool = False
) -> Tuple[Dict[str, str], Dict[str, Image.Image], List[MergedStrip], List[Tuple[Block, Image.Image, int, int]], Dict[str, str]]:
    """
    Вырезать кропы блоков из PDF, объединить TEXT/TABLE в полосы и сохранить.
    
    Args:
        pdf_path: путь к PDF файлу
        blocks: список блоков для вырезания
        output_dir: директория для сохранения кропов
        padding: отступ вокруг блоков
        save_image_crops_as_pdf: если True, сохранять IMAGE блоки как PDF (векторный формат)
    
    Returns:
        (
            strip_paths: dict strip_id -> путь к файлу,
            strip_images: dict strip_id -> PIL Image,
            strips: список MergedStrip,
            image_blocks: список (block, crop, part_idx, total_parts) для IMAGE блоков,
            image_pdf_paths: dict block_id -> путь к PDF-кропу (если save_image_crops_as_pdf=True)
        )
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Сначала вырезаем все кропы отдельных блоков в память
    block_crops: Dict[str, Image.Image] = {}
    image_pdf_paths: Dict[str, str] = {}
    
    # Группируем блоки по страницам
    blocks_by_page: Dict[int, List[Block]] = {}
    for block in blocks:
        page_idx = block.page_index
        if page_idx not in blocks_by_page:
            blocks_by_page[page_idx] = []
        blocks_by_page[page_idx].append(block)
    
    with PDFDocument(pdf_path) as pdf:
        # Открываем PDF через fitz для создания PDF-кропов IMAGE блоков
        pdf_doc = fitz.open(pdf_path) if save_image_crops_as_pdf else None
        
        try:
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
                        
                        # Для IMAGE блоков дополнительно создаём PDF-кроп
                        if save_image_crops_as_pdf and pdf_doc and block.block_type == BlockType.IMAGE:
                            pdf_crop_path = os.path.join(output_dir, f"image_{block.id}.pdf")
                            result = crop_block_to_pdf(pdf_doc, block, pdf_crop_path, padding, page_image)
                            if result:
                                image_pdf_paths[block.id] = result
                                block.image_file = result  # Сохраняем путь к PDF
                    except Exception as e:
                        logger.error(f"Ошибка при вырезании блока {block.id}: {e}")
        finally:
            if pdf_doc:
                pdf_doc.close()
    
    # Группируем в полосы
    strips, image_blocks = group_blocks_into_strips(blocks, block_crops)
    
    strip_paths: Dict[str, str] = {}
    strip_images: Dict[str, Image.Image] = {}
    
    # Объединённые кропы для полос TEXT/TABLE - только в память, не на диск
    for strip in strips:
        if not strip.crops:
            continue
        
        try:
            merged_image = merge_crops_vertically(strip.crops)
            strip_images[strip.strip_id] = merged_image
            logger.debug(f"Полоса {strip.strip_id}: {len(strip.blocks)} блоков, {merged_image.height}px")
        except Exception as e:
            logger.error(f"Ошибка создания полосы {strip.strip_id}: {e}")
    
    # IMAGE блоки - PNG на диск не сохраняем (только PDF если save_image_crops_as_pdf=True)
    for block, crop, part_idx, total_parts in image_blocks:
        logger.debug(f"IMAGE кроп {block.id} (часть {part_idx + 1}/{total_parts})")
    
    logger.info(f"Вырезано: {len(strip_paths)} полос, {len(image_blocks)} IMAGE блоков, {len(image_pdf_paths)} PDF-кропов")
    return strip_paths, strip_images, strips, image_blocks, image_pdf_paths
