"""Утилиты для вырезания кропов блоков из PDF страниц"""
from __future__ import annotations

import os
import logging
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field
from PIL import Image, ImageDraw
import fitz  # PyMuPDF

from rd_core.models import Block, BlockType, ShapeType
from rd_core.pdf_utils import PDFDocument

logger = logging.getLogger(__name__)

MAX_STRIP_HEIGHT = 9000
MAX_SINGLE_BLOCK_HEIGHT = 9000


@dataclass
class BlockPart:
    """Часть блока (для блоков >9000px)"""
    block: Block
    crop: Image.Image
    part_idx: int
    total_parts: int


@dataclass
class MergedStrip:
    """Объединённая полоса блоков TEXT/TABLE"""
    blocks: List[Block] = field(default_factory=list)
    crops: List[Image.Image] = field(default_factory=list)
    block_parts: List[BlockPart] = field(default_factory=list)
    total_height: int = 0
    max_width: int = 0
    strip_id: str = ""


def crop_block_from_image(page_image: Image.Image, block: Block, padding: int = 0) -> Image.Image:
    """Вырезать кроп блока из изображения страницы"""
    nx1, ny1, nx2, ny2 = block.coords_norm
    img_w, img_h = page_image.width, page_image.height
    
    x1, y1 = int(nx1 * img_w), int(ny1 * img_h)
    x2, y2 = int(nx2 * img_w), int(ny2 * img_h)
    
    # Padding с ограничением границ
    x1, y1 = max(0, x1 - padding), max(0, y1 - padding)
    x2, y2 = min(img_w, x2 + padding), min(img_h, y2 + padding)
    
    logger.debug(f"[CROP_IMAGE] {block.id}: [{x1},{y1},{x2},{y2}] size={x2-x1}x{y2-y1}")
    
    # Прямоугольник — простой crop
    if block.shape_type == ShapeType.RECTANGLE or not block.polygon_points:
        return page_image.crop((x1, y1, x2, y2))
    
    # Полигон — с маской
    crop_w, crop_h = x2 - x1, y2 - y1
    orig_x1, orig_y1, orig_x2, orig_y2 = block.coords_px
    bbox_w, bbox_h = orig_x2 - orig_x1, orig_y2 - orig_y1
    
    adjusted_points = []
    for px, py in block.polygon_points:
        norm_px = (px - orig_x1) / bbox_w if bbox_w else 0
        norm_py = (py - orig_y1) / bbox_h if bbox_h else 0
        adjusted_points.append((norm_px * crop_w, norm_py * crop_h))
    
    mask = Image.new('L', (crop_w, crop_h), 0)
    ImageDraw.Draw(mask).polygon(adjusted_points, fill=255)
    
    cropped = page_image.crop((x1, y1, x2, y2))
    result = Image.new('RGB', cropped.size, (255, 255, 255))
    result.paste(cropped, mask=mask)
    return result


def crop_block_to_pdf(pdf_doc: fitz.Document, block: Block, output_path: str, padding_pt: int = 2) -> Optional[str]:
    """Вырезать блок из PDF и сохранить как отдельный PDF"""
    try:
        page = pdf_doc[block.page_index]
        rect = page.rect
        rotation = page.rotation
        
        # Вычисляем clip в координатах page.rect
        nx1, ny1, nx2, ny2 = block.coords_norm
        x1_pt = max(rect.x0, rect.x0 + nx1 * rect.width - padding_pt)
        y1_pt = max(rect.y0, rect.y0 + ny1 * rect.height - padding_pt)
        x2_pt = min(rect.x1, rect.x0 + nx2 * rect.width + padding_pt)
        y2_pt = min(rect.y1, rect.y0 + ny2 * rect.height + padding_pt)
        
        clip_rect = fitz.Rect(x1_pt, y1_pt, x2_pt, y2_pt)
        
        # Деротация для show_pdf_page
        if rotation != 0:
            clip_rect = clip_rect * page.derotation_matrix
            clip_rect.normalize()
        
        # Размеры с учётом rotation
        if rotation in (90, 270):
            crop_width, crop_height = clip_rect.height, clip_rect.width
        else:
            crop_width, crop_height = clip_rect.width, clip_rect.height
        
        logger.debug(f"[CROP_PDF] {block.id}: clip={clip_rect}, size={crop_width:.1f}x{crop_height:.1f}, rot={rotation}")
        
        new_doc = fitz.open()
        new_page = new_doc.new_page(width=crop_width, height=crop_height)
        new_page.show_pdf_page(new_page.rect, pdf_doc, block.page_index, clip=clip_rect, rotate=-rotation)
        
        # Маска для полигонов
        if block.shape_type == ShapeType.POLYGON and block.polygon_points:
            orig_x1, orig_y1, orig_x2, orig_y2 = block.coords_px
            bbox_w, bbox_h = orig_x2 - orig_x1, orig_y2 - orig_y1
            
            polygon_pts = []
            for px, py in block.polygon_points:
                norm_px = (px - orig_x1) / bbox_w if bbox_w else 0
                norm_py = (py - orig_y1) / bbox_h if bbox_h else 0
                polygon_pts.append(fitz.Point(norm_px * crop_width, norm_py * crop_height))
            
            shape = new_page.new_shape()
            shape.draw_rect(new_page.rect)
            if polygon_pts:
                shape.draw_polyline(polygon_pts + [polygon_pts[0]])
            shape.finish(color=None, fill=(1, 1, 1), even_odd=True)
            shape.commit()
        
        new_doc.save(output_path, deflate=True, garbage=4)
        new_doc.close()
        
        logger.debug(f"  -> Saved: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Ошибка PDF-кропа {block.id}: {e}")
        return None


def split_large_crop(crop: Image.Image, max_height: int = MAX_SINGLE_BLOCK_HEIGHT, overlap: int = 100) -> List[Image.Image]:
    """Разделить большой кроп на части"""
    if crop.height <= max_height:
        return [crop]
    
    parts = []
    y = 0
    step = max_height - overlap
    
    while y < crop.height:
        y_end = min(y + max_height, crop.height)
        parts.append(crop.crop((0, y, crop.width, y_end)))
        y += step
        if crop.height - y < overlap:
            break
    
    logger.debug(f"Разделён кроп {crop.height}px на {len(parts)} частей")
    return parts


def merge_crops_vertically(crops: List[Image.Image], gap: int = 20) -> Image.Image:
    """Объединить кропы вертикально"""
    if not crops:
        raise ValueError("Список кропов пуст")
    if len(crops) == 1:
        return crops[0]
    
    max_width = max(c.width for c in crops)
    total_height = sum(c.height for c in crops) + gap * (len(crops) - 1)
    
    merged = Image.new('RGB', (max_width, total_height), (255, 255, 255))
    y_offset = 0
    
    for crop in crops:
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
    """Группировка TEXT/TABLE блоков в полосы, IMAGE блоки отдельно"""
    sorted_blocks = sorted(blocks, key=lambda b: (b.page_index, b.coords_px[1]))
    
    strips: List[MergedStrip] = []
    image_blocks: List[Tuple[Block, Image.Image, int, int]] = []
    current_strip = MergedStrip()
    strip_counter = 0
    
    for block in sorted_blocks:
        crop = block_crops.get(block.id)
        if not crop:
            continue
        
        if block.block_type == BlockType.IMAGE:
            # Закрываем текущую полосу
            if current_strip.blocks:
                strip_counter += 1
                current_strip.strip_id = f"strip_{strip_counter:04d}"
                strips.append(current_strip)
                current_strip = MergedStrip()
            
            # IMAGE блоки отдельно
            crop_parts = split_large_crop(crop)
            for part_idx, part in enumerate(crop_parts):
                image_blocks.append((block, part, part_idx, len(crop_parts)))
            continue
        
        # TEXT/TABLE
        crop_parts = split_large_crop(crop)
        for part_idx, crop_part in enumerate(crop_parts):
            if current_strip.total_height + crop_part.height > MAX_STRIP_HEIGHT and current_strip.blocks:
                strip_counter += 1
                current_strip.strip_id = f"strip_{strip_counter:04d}"
                strips.append(current_strip)
                current_strip = MergedStrip()
            
            current_strip.blocks.append(block)
            current_strip.crops.append(crop_part)
            current_strip.block_parts.append(BlockPart(block, crop_part, part_idx, len(crop_parts)))
            current_strip.total_height += crop_part.height + 20
            current_strip.max_width = max(current_strip.max_width, crop_part.width)
    
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
    """Вырезать кропы блоков из PDF, объединить TEXT/TABLE в полосы"""
    os.makedirs(output_dir, exist_ok=True)
    
    block_crops: Dict[str, Image.Image] = {}
    image_pdf_paths: Dict[str, str] = {}
    
    # Группируем по страницам
    blocks_by_page: Dict[int, List[Block]] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page_index, []).append(block)
    
    with PDFDocument(pdf_path) as pdf:
        pdf_doc = fitz.open(pdf_path) if save_image_crops_as_pdf else None
        
        try:
            for page_idx in sorted(blocks_by_page.keys()):
                page_image = pdf.render_page(page_idx)
                if page_image is None:
                    logger.error(f"Не удалось отрендерить страницу {page_idx}")
                    continue
                
                for block in blocks_by_page[page_idx]:
                    try:
                        block_crops[block.id] = crop_block_from_image(page_image, block, padding)
                        
                        if save_image_crops_as_pdf and pdf_doc and block.block_type == BlockType.IMAGE:
                            pdf_crop_path = os.path.join(output_dir, f"image_{block.id}.pdf")
                            result = crop_block_to_pdf(pdf_doc, block, pdf_crop_path, padding_pt=2)
                            if result:
                                image_pdf_paths[block.id] = result
                                block.image_file = result
                    except Exception as e:
                        logger.error(f"Ошибка вырезания блока {block.id}: {e}")
        finally:
            if pdf_doc:
                pdf_doc.close()
    
    strips, image_blocks = group_blocks_into_strips(blocks, block_crops)
    
    strip_paths: Dict[str, str] = {}
    strip_images: Dict[str, Image.Image] = {}
    
    for strip in strips:
        if strip.crops:
            try:
                strip_images[strip.strip_id] = merge_crops_vertically(strip.crops)
            except Exception as e:
                logger.error(f"Ошибка создания полосы {strip.strip_id}: {e}")
    
    logger.info(f"Вырезано: {len(strip_images)} полос, {len(image_blocks)} IMAGE, {len(image_pdf_paths)} PDF-кропов")
    return strip_paths, strip_images, strips, image_blocks, image_pdf_paths
