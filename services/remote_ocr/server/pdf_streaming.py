"""
Streaming обработка PDF через fitz (PyMuPDF)
Оптимизация памяти: страницы обрабатываются по одной и сразу освобождаются
"""
from __future__ import annotations

import gc
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Generator, Iterator, List, Optional, Tuple

import fitz
from PIL import Image, ImageDraw

from .memory_utils import log_memory, get_pil_image_size_mb
from .settings import settings

logger = logging.getLogger(__name__)

# Константы из настроек
PDF_RENDER_DPI = settings.pdf_render_dpi
PDF_RENDER_ZOOM = PDF_RENDER_DPI / 72.0
MAX_STRIP_HEIGHT = settings.max_strip_height
MAX_SINGLE_BLOCK_HEIGHT = settings.max_strip_height
MAX_IMAGE_PIXELS = 400_000_000

# Увеличиваем лимит PIL
Image.MAX_IMAGE_PIXELS = 500_000_000


@dataclass
class BlockPart:
    """Часть блока (для блоков >9000px)"""
    block: object  # Block
    crop: Image.Image
    part_idx: int
    total_parts: int


@dataclass
class MergedStrip:
    """Объединённая полоса блоков TEXT/TABLE"""
    blocks: List = field(default_factory=list)
    crops: List[Image.Image] = field(default_factory=list)
    block_parts: List[BlockPart] = field(default_factory=list)
    total_height: int = 0
    max_width: int = 0
    strip_id: str = ""


class StreamingPDFProcessor:
    """
    Streaming процессор PDF с оптимизацией памяти.
    Обрабатывает страницы последовательно, освобождая память после каждой.
    """
    
    def __init__(self, pdf_path: str, zoom: float = PDF_RENDER_ZOOM):
        self.pdf_path = pdf_path
        self.zoom = zoom
        self._doc: Optional[fitz.Document] = None
        self._current_page_idx: int = -1
        self._current_page_image: Optional[Image.Image] = None
    
    def __enter__(self):
        self._doc = fitz.open(self.pdf_path)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release_page_image()
        if self._doc:
            self._doc.close()
            self._doc = None
        gc.collect()
    
    @property
    def page_count(self) -> int:
        return len(self._doc) if self._doc else 0
    
    def _release_page_image(self):
        """Освободить текущее изображение страницы"""
        if self._current_page_image:
            self._current_page_image.close()
            self._current_page_image = None
            self._current_page_idx = -1
    
    def _get_effective_zoom(self, page: fitz.Page) -> float:
        """Вычислить zoom с учётом лимита пикселей"""
        rect = page.rect
        estimated = (rect.width * self.zoom) * (rect.height * self.zoom)
        if estimated > MAX_IMAGE_PIXELS:
            return (MAX_IMAGE_PIXELS / (rect.width * rect.height)) ** 0.5
        return self.zoom
    
    def get_page_image(self, page_idx: int) -> Optional[Image.Image]:
        """
        Получить изображение страницы (lazy loading).
        Кэширует текущую страницу, освобождает предыдущую.
        """
        if page_idx == self._current_page_idx and self._current_page_image:
            return self._current_page_image
        
        # Освобождаем предыдущую
        self._release_page_image()
        
        if not self._doc or page_idx < 0 or page_idx >= len(self._doc):
            return None
        
        try:
            page = self._doc[page_idx]
            effective_zoom = self._get_effective_zoom(page)
            mat = fitz.Matrix(effective_zoom, effective_zoom)
            
            # Рендерим напрямую в samples (RGB) вместо PNG
            pix = page.get_pixmap(matrix=mat)
            
            # Прямое создание Image из samples (быстрее чем через PNG)
            if pix.alpha:
                mode = "RGBA"
            else:
                mode = "RGB"
            
            self._current_page_image = Image.frombytes(
                mode, (pix.width, pix.height), pix.samples
            )
            self._current_page_idx = page_idx
            
            # Логируем размер страницы
            page_mb = get_pil_image_size_mb(self._current_page_image)
            logger.info(f"Page {page_idx} rendered: {pix.width}x{pix.height} (~{page_mb:.1f} MB, zoom={effective_zoom:.2f})")
            
            # Освобождаем pixmap
            pix = None
            
            return self._current_page_image
            
        except Exception as e:
            logger.error(f"Error rendering page {page_idx}: {e}")
            return None
    
    def get_page_dimensions(self, page_idx: int) -> Optional[Tuple[int, int]]:
        """Получить размеры страницы"""
        if not self._doc or page_idx < 0 or page_idx >= len(self._doc):
            return None
        page = self._doc[page_idx]
        rect = page.rect
        zoom = self._get_effective_zoom(page)
        return (int(rect.width * zoom), int(rect.height * zoom))
    
    def crop_block_image(self, block, padding: int = 5) -> Optional[Image.Image]:
        """Вырезать кроп блока из текущей страницы"""
        page_image = self.get_page_image(block.page_index)
        if not page_image:
            return None
        
        from rd_core.models import ShapeType
        
        nx1, ny1, nx2, ny2 = block.coords_norm
        img_w, img_h = page_image.width, page_image.height
        
        x1, y1 = int(nx1 * img_w), int(ny1 * img_h)
        x2, y2 = int(nx2 * img_w), int(ny2 * img_h)
        
        x1, y1 = max(0, x1 - padding), max(0, y1 - padding)
        x2, y2 = min(img_w, x2 + padding), min(img_h, y2 + padding)
        
        if block.shape_type == ShapeType.RECTANGLE or not block.polygon_points:
            return page_image.crop((x1, y1, x2, y2)).copy()
        
        # Полигон с маской
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
        mask.close()
        
        return result
    
    def crop_block_to_pdf(self, block, output_path: str, padding_pt: int = 2) -> Optional[str]:
        """Вырезать блок как PDF"""
        if not self._doc:
            return None
        
        from rd_core.models import ShapeType
        
        try:
            page = self._doc[block.page_index]
            rect = page.rect
            rotation = page.rotation
            
            nx1, ny1, nx2, ny2 = block.coords_norm
            x1_pt = max(rect.x0, rect.x0 + nx1 * rect.width - padding_pt)
            y1_pt = max(rect.y0, rect.y0 + ny1 * rect.height - padding_pt)
            x2_pt = min(rect.x1, rect.x0 + nx2 * rect.width + padding_pt)
            y2_pt = min(rect.y1, rect.y0 + ny2 * rect.height + padding_pt)
            
            clip_rect = fitz.Rect(x1_pt, y1_pt, x2_pt, y2_pt)
            
            if rotation != 0:
                clip_rect = clip_rect * page.derotation_matrix
                clip_rect.normalize()
            
            if rotation in (90, 270):
                crop_width, crop_height = clip_rect.height, clip_rect.width
            else:
                crop_width, crop_height = clip_rect.width, clip_rect.height
            
            new_doc = fitz.open()
            new_page = new_doc.new_page(width=crop_width, height=crop_height)
            new_page.show_pdf_page(new_page.rect, self._doc, block.page_index, clip=clip_rect, rotate=-rotation)
            
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
            
            return output_path
            
        except Exception as e:
            logger.error(f"PDF crop error {block.id}: {e}")
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
        parts.append(crop.crop((0, y, crop.width, y_end)).copy())
        y += step
        if crop.height - y < overlap:
            break
    
    return parts


BLOCK_SEPARATOR_HEIGHT = 80


def create_block_separator(block_id: str, width: int, height: int = BLOCK_SEPARATOR_HEIGHT) -> Image.Image:
    """
    Создать черную полосу-разделитель с белым текстом block_id.
    """
    from PIL import ImageFont
    separator = Image.new('RGB', (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(separator)
    
    text = f"[[[BLOCK_ID: {block_id}]]]"
    
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype("DejaVuSansMono.ttf", 48)
        except (IOError, OSError):
            font = ImageFont.load_default(size=48)
    
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    return separator


def merge_crops_vertically(
    crops: List[Image.Image], 
    gap: int = 20,
    block_ids: Optional[List[str]] = None
) -> Image.Image:
    """
    Объединить кропы вертикально с опциональными разделителями block_id.
    Разделитель вставляется только при смене block_id (не перед каждой частью блока).
    """
    if not crops:
        raise ValueError("Empty crops list")
    
    use_separators = block_ids is not None and len(block_ids) == len(crops)
    max_width = max(c.width for c in crops)
    
    # Считаем количество уникальных переходов между блоками
    if use_separators:
        separator_count = 0
        prev_id = None
        for bid in block_ids:
            if bid != prev_id:
                separator_count += 1
                prev_id = bid
        separator_height = BLOCK_SEPARATOR_HEIGHT
        total_height = sum(c.height for c in crops) + separator_height * separator_count + gap * (len(crops) - separator_count)
    else:
        total_height = sum(c.height for c in crops) + gap * (len(crops) - 1)
    
    merged = Image.new('RGB', (max_width, total_height), (255, 255, 255))
    y_offset = 0
    prev_block_id = None
    
    for i, crop in enumerate(crops):
        if use_separators:
            current_block_id = block_ids[i]
            if current_block_id != prev_block_id:
                # Новый блок - вставляем разделитель
                separator = create_block_separator(current_block_id, max_width)
                merged.paste(separator, (0, y_offset))
                y_offset += separator.height
                prev_block_id = current_block_id
            elif i > 0:
                # Часть того же блока - только gap
                y_offset += gap
        elif i > 0:
            y_offset += gap
        
        x_offset = (max_width - crop.width) // 2
        if crop.mode in ('RGBA', 'LA'):
            crop = crop.convert('RGB')
        merged.paste(crop, (x_offset, y_offset))
        y_offset += crop.height
    
    return merged


def streaming_crop_and_merge(
    pdf_path: str,
    blocks: List,
    output_dir: str,
    padding: int = 5,
    save_image_crops_as_pdf: bool = False
) -> Tuple[Dict[str, str], Dict[str, Image.Image], List[MergedStrip], List[Tuple], Dict[str, str]]:
    """
    Streaming версия crop_and_merge_blocks_from_pdf.
    Обрабатывает страницы последовательно, освобождая память.
    """
    from rd_core.models import BlockType
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Логируем размер PDF
    pdf_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    start_mem = log_memory(f"streaming_crop_and_merge start (PDF: {pdf_size_mb:.1f} MB)")
    
    # Группируем по страницам
    blocks_by_page: Dict[int, List] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page_index, []).append(block)
    
    block_crops: Dict[str, Image.Image] = {}
    image_pdf_paths: Dict[str, str] = {}
    total_crops_mb = 0.0
    
    with StreamingPDFProcessor(pdf_path) as processor:
        logger.info(f"PDF pages: {processor.page_count}, blocks pages: {len(blocks_by_page)}")
        
        # Обрабатываем страницы последовательно
        for page_idx in sorted(blocks_by_page.keys()):
            page_blocks = blocks_by_page[page_idx]
            page_crops_mb = 0.0
            
            for block in page_blocks:
                try:
                    crop = processor.crop_block_image(block, padding)
                    if crop:
                        block_crops[block.id] = crop
                        page_crops_mb += get_pil_image_size_mb(crop)
                    
                    if save_image_crops_as_pdf and block.block_type == BlockType.IMAGE:
                        pdf_crop_path = os.path.join(output_dir, f"image_{block.id}.pdf")
                        result = processor.crop_block_to_pdf(block, pdf_crop_path, padding_pt=2)
                        if result:
                            image_pdf_paths[block.id] = result
                            block.image_file = result
                            
                except Exception as e:
                    logger.error(f"Error processing block {block.id}: {e}")
            
            total_crops_mb += page_crops_mb
            logger.debug(f"Page {page_idx}: {len(page_blocks)} blocks, crops: {page_crops_mb:.1f} MB")
        
        # Группируем в полосы
        strips, image_blocks = _group_blocks_streaming(blocks, block_crops)
    
    log_memory(f"После обработки страниц (block_crops: ~{total_crops_mb:.1f} MB)")
    
    # Создаём merged images для полос
    strip_paths: Dict[str, str] = {}
    strip_images: Dict[str, Image.Image] = {}
    
    for strip in strips:
        if strip.crops:
            try:
                # Извлекаем block_ids из block_parts для разделителей
                block_ids = [bp.block.id for bp in strip.block_parts]
                strip_images[strip.strip_id] = merge_crops_vertically(strip.crops, block_ids=block_ids)
                # Освобождаем исходные кропы полосы (они скопированы в merged)
                for crop in strip.crops:
                    try:
                        crop.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Error creating strip {strip.strip_id}: {e}")
        strip.crops.clear()  # Очищаем список
    
    # Очищаем block_crops - они больше не нужны (скопированы в strips/image_blocks)
    for block_id, crop in list(block_crops.items()):
        # Не закрываем - они уже закрыты или используются в image_blocks
        pass
    block_crops.clear()
    
    gc.collect()
    
    strips_mb = sum(get_pil_image_size_mb(img) for img in strip_images.values())
    images_mb = sum(get_pil_image_size_mb(crop) for _, crop, _, _ in image_blocks)
    log_memory(f"После merge (strips: ~{strips_mb:.1f} MB, images: ~{images_mb:.1f} MB)")
    
    logger.info(f"Streaming done: {len(strip_images)} strips, {len(image_blocks)} images, {len(image_pdf_paths)} PDF crops")
    return strip_paths, strip_images, strips, image_blocks, image_pdf_paths


def _group_blocks_streaming(
    blocks: List,
    block_crops: Dict[str, Image.Image]
) -> Tuple[List[MergedStrip], List[Tuple]]:
    """Группировка блоков в полосы (streaming-safe)"""
    from rd_core.models import BlockType
    
    strips: List[MergedStrip] = []
    image_blocks: List[Tuple] = []
    current_strip = MergedStrip()
    strip_counter = 0
    
    for block in blocks:
        crop = block_crops.get(block.id)
        if not crop:
            continue
        
        if block.block_type == BlockType.IMAGE:
            if current_strip.blocks:
                strip_counter += 1
                current_strip.strip_id = f"strip_{strip_counter:04d}"
                strips.append(current_strip)
                current_strip = MergedStrip()
            
            crop_parts = split_large_crop(crop)
            for part_idx, part in enumerate(crop_parts):
                image_blocks.append((block, part, part_idx, len(crop_parts)))
            continue
        
        # TEXT/TABLE
        crop_parts = split_large_crop(crop)
        for part_idx, crop_part in enumerate(crop_parts):
            # gap добавляется только между блоками (не перед первым)
            gap = 20 if current_strip.blocks else 0
            new_height = crop_part.height + gap
            
            if current_strip.total_height + new_height > MAX_STRIP_HEIGHT and current_strip.blocks:
                strip_counter += 1
                current_strip.strip_id = f"strip_{strip_counter:04d}"
                strips.append(current_strip)
                current_strip = MergedStrip()
                gap = 0  # первый блок в новой полосе без gap
                new_height = crop_part.height
            
            current_strip.blocks.append(block)
            current_strip.crops.append(crop_part)
            current_strip.block_parts.append(BlockPart(block, crop_part, part_idx, len(crop_parts)))
            current_strip.total_height += new_height
            current_strip.max_width = max(current_strip.max_width, crop_part.width)
    
    if current_strip.blocks:
        strip_counter += 1
        current_strip.strip_id = f"strip_{strip_counter:04d}"
        strips.append(current_strip)
    
    return strips, image_blocks


def get_page_dimensions_streaming(pdf_path: str) -> Dict[int, Tuple[int, int]]:
    """Получить размеры всех страниц без полного рендеринга"""
    dims = {}
    with StreamingPDFProcessor(pdf_path) as processor:
        for i in range(processor.page_count):
            d = processor.get_page_dimensions(i)
            if d:
                dims[i] = d
    return dims

