"""
Streaming обработка PDF через fitz (PyMuPDF)
Оптимизация памяти: страницы обрабатываются по одной и сразу освобождаются
"""
from __future__ import annotations

import gc
import math
from typing import Dict, List, Optional, Tuple

import fitz
from PIL import Image, ImageDraw

from rd_core.pdf_utils import normalize_coords_norm

from .logging_config import get_logger
from .memory_utils import get_pil_image_size_mb
from .settings import settings

logger = get_logger(__name__)

# Константы из настроек
PDF_RENDER_DPI = settings.pdf_render_dpi
PDF_RENDER_ZOOM = PDF_RENDER_DPI / 72.0
MAX_STRIP_HEIGHT = settings.max_strip_height
MAX_SINGLE_BLOCK_HEIGHT = settings.max_strip_height
MAX_IMAGE_PIXELS = 400_000_000

# Увеличиваем лимит PIL
Image.MAX_IMAGE_PIXELS = 500_000_000


def _log_box_mismatch_if_any(block, rect, cropbox, mediabox, rotation: int) -> None:
    """INFO-лог при расхождении MediaBox/CropBox/rect (CAD-чертежи, rotation)."""
    if (
        abs(cropbox.x0 - mediabox.x0) > 0.5
        or abs(cropbox.y0 - mediabox.y0) > 0.5
        or abs(cropbox.width - mediabox.width) > 0.5
        or abs(cropbox.height - mediabox.height) > 0.5
        or abs(cropbox.x0 - rect.x0) > 0.5
        or abs(cropbox.y0 - rect.y0) > 0.5
        or rotation != 0
    ):
        logger.info(
            "PDF crop box mismatch block=%s page=%d: "
            "rect=(%.1f,%.1f,%.1f,%.1f) "
            "cropbox=(%.1f,%.1f,%.1f,%.1f) "
            "mediabox=(%.1f,%.1f,%.1f,%.1f) rotation=%d",
            block.id,
            block.page_index,
            rect.x0, rect.y0, rect.x1, rect.y1,
            cropbox.x0, cropbox.y0, cropbox.x1, cropbox.y1,
            mediabox.x0, mediabox.y0, mediabox.x1, mediabox.y1,
            rotation,
        )


def _visual_clip_to_source_clip(
    visual_clip: "fitz.Rect", page: "fitz.Page", cropbox: "fitz.Rect"
) -> Optional["fitz.Rect"]:
    """Перевести клип из визуального page.rect-пространства (anchored at 0,0)
    в нативное PDF-пространство страницы-источника (cropbox-anchored).
    Используется при создании PDF-кропа через show_pdf_page(clip=...).
    """
    rotation = page.rotation
    if rotation == 0:
        source = fitz.Rect(
            cropbox.x0 + visual_clip.x0,
            cropbox.y0 + visual_clip.y0,
            cropbox.x0 + visual_clip.x1,
            cropbox.y0 + visual_clip.y1,
        )
    else:
        try:
            source = visual_clip * page.derotation_matrix
            source.normalize()
        except Exception:
            return None

    coords = (source.x0, source.y0, source.x1, source.y1)
    if not all(math.isfinite(v) for v in coords):
        return None
    if source.width <= 0 or source.height <= 0:
        return None
    return source


def _polygon_to_crop_points(
    polygon_points,
    coords_px,
    pad_left: float,
    pad_top: float,
    bbox_w_in_crop: float,
    bbox_h_in_crop: float,
):
    """Преобразовать polygon_points (в клиентских пикселях) в координаты
    crop-изображения с учётом padding слева/сверху.

    polygon_points нормализуется по bbox блока (DPI-независимая доля 0..1),
    затем размещается в crop так, чтобы (0,0) полигона соответствовал
    (pad_left, pad_top), а (1,1) — (pad_left + bbox_w_in_crop, pad_top + bbox_h_in_crop).
    """
    orig_x1, orig_y1, orig_x2, orig_y2 = coords_px
    bbox_w = orig_x2 - orig_x1
    bbox_h = orig_y2 - orig_y1
    points = []
    for px, py in polygon_points:
        norm_px = (px - orig_x1) / bbox_w if bbox_w else 0
        norm_py = (py - orig_y1) / bbox_h if bbox_h else 0
        points.append(
            (pad_left + norm_px * bbox_w_in_crop, pad_top + norm_py * bbox_h_in_crop)
        )
    return points


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
            logger.info(
                f"Page {page_idx} rendered: {pix.width}x{pix.height} (~{page_mb:.1f} MB, zoom={effective_zoom:.2f})"
            )

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

    def _render_clip(
        self, page_idx: int, nx1: float, ny1: float, nx2: float, ny2: float, padding_px: int
    ) -> Optional[Image.Image]:
        """Отрендерить только указанную область страницы (без full-page raster).

        Возвращает PIL.Image нужного фрагмента в том же DPI/zoom, что и full-page,
        либо None если рендер не удался (caller должен fallback'нуть на старый путь).
        """
        if not self._doc or page_idx < 0 or page_idx >= len(self._doc):
            return None
        try:
            page = self._doc[page_idx]
            effective_zoom = self._get_effective_zoom(page)
            rect = page.rect
            if rect.width <= 0 or rect.height <= 0:
                return None

            # Padding в пикселях → в pdf-points через тот же zoom.
            pad_pt = padding_px / effective_zoom if effective_zoom > 0 else 0.0

            x1_pt = max(rect.x0, rect.x0 + nx1 * rect.width - pad_pt)
            y1_pt = max(rect.y0, rect.y0 + ny1 * rect.height - pad_pt)
            x2_pt = min(rect.x1, rect.x0 + nx2 * rect.width + pad_pt)
            y2_pt = min(rect.y1, rect.y0 + ny2 * rect.height + pad_pt)

            if x2_pt <= x1_pt or y2_pt <= y1_pt:
                return None

            clip = fitz.Rect(x1_pt, y1_pt, x2_pt, y2_pt)
            mat = fitz.Matrix(effective_zoom, effective_zoom)
            pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
            if pix.width <= 0 or pix.height <= 0:
                return None

            mode = "RGBA" if pix.alpha else "RGB"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            if mode != "RGB":
                img = img.convert("RGB")
            pix = None
            return img
        except Exception as e:
            logger.warning(
                "Clipped crop render failed for page %s: %s (fallback to full-page)",
                page_idx, e,
            )
            return None

    def crop_block_image(self, block, padding: int = 5) -> Optional[Image.Image]:
        """Вырезать кроп блока без полного рендера страницы.

        Стратегия:
        1) Пробуем отрендерить только нужный clip через fitz get_pixmap(clip=...).
           Это в разы быстрее full-page raster для типичных PDF, где блоки занимают
           малую часть страницы. DPI/padding/геометрия идентичны старому пути.
        2) Для polygon — рендерим bbox-clip и поверх кладём ту же polygon-маску.
        3) При любой ошибке clipped рендера — откатываемся на старый full-page путь
           через get_page_image(), сохраняя 100% совместимости.
        """
        from rd_core.models import ShapeType

        normalized_coords = normalize_coords_norm(block.coords_norm)
        if normalized_coords is None:
            logger.warning(
                "Invalid normalized coordinates for block %s on page %s: %s",
                block.id,
                block.page_index,
                block.coords_norm,
            )
            return None

        nx1, ny1, nx2, ny2 = normalized_coords

        # 1) Быстрый clipped path
        clipped = self._render_clip(block.page_index, nx1, ny1, nx2, ny2, padding)
        if clipped is not None:
            if block.shape_type == ShapeType.RECTANGLE or not block.polygon_points:
                return clipped

            # Polygon: накладываем маску поверх clipped изображения c учётом padding.
            crop_w, crop_h = clipped.width, clipped.height
            orig_x1, orig_y1, orig_x2, orig_y2 = block.coords_px
            bbox_w, bbox_h = orig_x2 - orig_x1, orig_y2 - orig_y1

            if crop_w > 0 and crop_h > 0 and bbox_w > 0 and bbox_h > 0:
                try:
                    # Перевычисляем visual_clip и зум, чтобы знать реальный padding
                    # с каждой стороны (он может быть обрезан границей страницы).
                    page = self._doc[block.page_index]
                    rect = page.rect
                    zoom = self._get_effective_zoom(page)
                    pad_pt = padding / zoom if zoom > 0 else 0.0
                    bbox_x1_pt = rect.x0 + nx1 * rect.width
                    bbox_y1_pt = rect.y0 + ny1 * rect.height
                    bbox_x2_pt = rect.x0 + nx2 * rect.width
                    bbox_y2_pt = rect.y0 + ny2 * rect.height
                    vx1 = max(rect.x0, bbox_x1_pt - pad_pt)
                    vy1 = max(rect.y0, bbox_y1_pt - pad_pt)
                    vx2 = min(rect.x1, bbox_x2_pt + pad_pt)
                    vy2 = min(rect.y1, bbox_y2_pt + pad_pt)

                    pad_left_px = (bbox_x1_pt - vx1) * zoom
                    pad_top_px = (bbox_y1_pt - vy1) * zoom
                    bbox_w_in_crop = (bbox_x2_pt - bbox_x1_pt) * zoom
                    bbox_h_in_crop = (bbox_y2_pt - bbox_y1_pt) * zoom

                    adjusted_points = _polygon_to_crop_points(
                        block.polygon_points,
                        block.coords_px,
                        pad_left_px, pad_top_px,
                        bbox_w_in_crop, bbox_h_in_crop,
                    )

                    mask = Image.new("L", (crop_w, crop_h), 0)
                    ImageDraw.Draw(mask).polygon(adjusted_points, fill=255)
                    result = Image.new("RGB", clipped.size, (255, 255, 255))
                    result.paste(clipped, mask=mask)
                    mask.close()
                    clipped.close()
                    return result
                except Exception as e:
                    logger.warning(
                        "Polygon mask on clipped crop failed for block %s: %s "
                        "(fallback to full-page)", block.id, e,
                    )
                    clipped.close()
            else:
                return clipped

        # 2) Fallback: старый full-page путь
        page_image = self.get_page_image(block.page_index)
        if not page_image:
            return None

        img_w, img_h = page_image.width, page_image.height
        x1, y1 = int(nx1 * img_w), int(ny1 * img_h)
        x2, y2 = int(nx2 * img_w), int(ny2 * img_h)
        x1, y1 = max(0, x1 - padding), max(0, y1 - padding)
        x2, y2 = min(img_w, x2 + padding), min(img_h, y2 + padding)

        if x2 <= x1 or y2 <= y1:
            logger.warning(
                "Empty raster crop for block %s on page %s after padding: %s",
                block.id,
                block.page_index,
                (x1, y1, x2, y2),
            )
            return None

        if block.shape_type == ShapeType.RECTANGLE or not block.polygon_points:
            return page_image.crop((x1, y1, x2, y2)).copy()

        crop_w, crop_h = x2 - x1, y2 - y1
        orig_x1, orig_y1, orig_x2, orig_y2 = block.coords_px
        bbox_w, bbox_h = orig_x2 - orig_x1, orig_y2 - orig_y1

        if crop_w <= 0 or crop_h <= 0 or bbox_w <= 0 or bbox_h <= 0:
            return page_image.crop((x1, y1, x2, y2)).copy()

        # bbox без padding в пикселях полной страницы
        bx1 = int(nx1 * img_w)
        by1 = int(ny1 * img_h)
        bx2 = int(nx2 * img_w)
        by2 = int(ny2 * img_h)
        pad_left_px = bx1 - x1
        pad_top_px = by1 - y1
        bbox_w_in_crop = bx2 - bx1
        bbox_h_in_crop = by2 - by1

        adjusted_points = _polygon_to_crop_points(
            block.polygon_points,
            block.coords_px,
            pad_left_px, pad_top_px,
            bbox_w_in_crop, bbox_h_in_crop,
        )

        mask = Image.new("L", (crop_w, crop_h), 0)
        ImageDraw.Draw(mask).polygon(adjusted_points, fill=255)

        cropped = page_image.crop((x1, y1, x2, y2))
        result = Image.new("RGB", cropped.size, (255, 255, 255))
        result.paste(cropped, mask=mask)
        mask.close()

        return result

    def crop_block_to_pdf(
        self, block, output_path: str, padding_pt: int = 2
    ) -> Optional[str]:
        """Вырезать блок как PDF.

        Стратегия:
        1. Считаем visual bbox в page.rect-пространстве (visual, anchored at 0,0).
           coords_norm нормализованы клиентом относительно этой системы.
        2. Переводим visual_clip → source_clip (cropbox-anchored, до ротации) через
           helper, который для rotation=0 делает offset на cropbox.x0/y0, а для
           rotation in (90,270) применяет page.derotation_matrix.
        3. Создаём новую PDF-страницу размером visual_clip (визуальные W,H —
           они уже корректные для повёрнутых страниц), и show_pdf_page копирует
           source_clip с rotate=-rotation, чтобы контент встал «как видит пользователь».
        4. Polygon-маска накладывается в координатах нового кропа c учётом padding.
        """
        if not self._doc:
            return None

        from rd_core.models import ShapeType

        try:
            page = self._doc[block.page_index]
            rect = page.rect
            rotation = page.rotation
            cropbox = page.cropbox
            mediabox = page.mediabox

            # Диагностика mismatch box-ов (CAD-чертежи / ротация)
            _log_box_mismatch_if_any(block, rect, cropbox, mediabox, rotation)

            normalized_coords = normalize_coords_norm(block.coords_norm)
            if normalized_coords is None:
                logger.warning(
                    "Skipping PDF crop for block %s on page %s due to invalid coords: %s",
                    block.id,
                    block.page_index,
                    block.coords_norm,
                )
                return None
            nx1, ny1, nx2, ny2 = normalized_coords

            if rect.width <= 0 or rect.height <= 0:
                return None

            # 1) Визуальный bbox блока без padding (в page.rect-coordinates)
            bbox_x1_pt = rect.x0 + nx1 * rect.width
            bbox_y1_pt = rect.y0 + ny1 * rect.height
            bbox_x2_pt = rect.x0 + nx2 * rect.width
            bbox_y2_pt = rect.y0 + ny2 * rect.height

            # 2) Визуальный clip = bbox + padding, прижатый к границам page.rect
            vx1 = max(rect.x0, bbox_x1_pt - padding_pt)
            vy1 = max(rect.y0, bbox_y1_pt - padding_pt)
            vx2 = min(rect.x1, bbox_x2_pt + padding_pt)
            vy2 = min(rect.y1, bbox_y2_pt + padding_pt)
            if vx2 <= vx1 or vy2 <= vy1:
                logger.warning(
                    "Skipping PDF crop for block %s on page %s due to empty visual clip",
                    block.id, block.page_index,
                )
                return None
            visual_clip = fitz.Rect(vx1, vy1, vx2, vy2)

            # 3) Переводим в source-space (cropbox-anchored, до ротации)
            source_clip = _visual_clip_to_source_clip(visual_clip, page, cropbox)
            if source_clip is None:
                logger.warning(
                    "Skipping PDF crop for block %s on page %s due to invalid source clip",
                    block.id, block.page_index,
                )
                return None

            crop_width = visual_clip.width
            crop_height = visual_clip.height
            if crop_width <= 0 or crop_height <= 0:
                return None

            logger.info(
                "PDF crop block=%s page=%d rotation=%d "
                "coords_norm=(%.4f,%.4f,%.4f,%.4f) "
                "rect=(%.1f,%.1f,%.1f,%.1f) cropbox=(%.1f,%.1f,%.1f,%.1f) "
                "visual_clip=(%.1f,%.1f,%.1f,%.1f) source_clip=(%.1f,%.1f,%.1f,%.1f) "
                "crop_size=%.1fx%.1f",
                block.id, block.page_index, rotation,
                nx1, ny1, nx2, ny2,
                rect.x0, rect.y0, rect.x1, rect.y1,
                cropbox.x0, cropbox.y0, cropbox.x1, cropbox.y1,
                visual_clip.x0, visual_clip.y0, visual_clip.x1, visual_clip.y1,
                source_clip.x0, source_clip.y0, source_clip.x1, source_clip.y1,
                crop_width, crop_height,
            )

            # 4) Сборка нового PDF.
            # show_pdf_page пересекает clip с ВИЗУАЛЬНЫМ page.rect источника, тогда как
            # source_clip посчитан в нативном (до-ротации) cropbox-пространстве. На
            # повёрнутых страницах временно снимаем поворот источника (поворот учтён в
            # source_clip через derotation_matrix + rotate=-rotation). Иначе clip уходит
            # за визуальный rect → либо ValueError "clip must be finite and not empty",
            # либо неверный регион кропа.
            new_doc = fitz.open()
            new_page = new_doc.new_page(width=crop_width, height=crop_height)
            if rotation:
                page.set_rotation(0)
            try:
                new_page.show_pdf_page(
                    new_page.rect,
                    self._doc,
                    block.page_index,
                    clip=source_clip,
                    rotate=-rotation,
                )
            finally:
                if rotation:
                    page.set_rotation(rotation)

            # 5) Polygon-маска (если форма — полигон) в координатах нового кропа
            if block.shape_type == ShapeType.POLYGON and block.polygon_points:
                pad_left = bbox_x1_pt - visual_clip.x0
                pad_top = bbox_y1_pt - visual_clip.y0
                bbox_w_in_crop = bbox_x2_pt - bbox_x1_pt
                bbox_h_in_crop = bbox_y2_pt - bbox_y1_pt

                if bbox_w_in_crop > 0 and bbox_h_in_crop > 0:
                    points = _polygon_to_crop_points(
                        block.polygon_points,
                        block.coords_px,
                        pad_left, pad_top,
                        bbox_w_in_crop, bbox_h_in_crop,
                    )
                    polygon_pts = [fitz.Point(x, y) for x, y in points]
                    if polygon_pts:
                        shape = new_page.new_shape()
                        shape.draw_rect(new_page.rect)
                        shape.draw_polyline(polygon_pts + [polygon_pts[0]])
                        shape.finish(color=None, fill=(1, 1, 1), even_odd=True)
                        shape.commit()

            new_doc.save(output_path, deflate=True, garbage=4)
            new_doc.close()

            return output_path

        except Exception as e:
            # Не fatal: вызывающий код в pass1_crops оставляет PNG-кроп для блока,
            # OCR пройдёт по нему. Логируем как warning + stack trace для разбора.
            logger.warning(f"PDF crop error {block.id}: {e}", exc_info=True)
            return None


def split_large_crop(
    crop: Image.Image, max_height: int = MAX_SINGLE_BLOCK_HEIGHT, overlap: int = 100
) -> List[Image.Image]:
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


BLOCK_SEPARATOR_HEIGHT = 60


def create_block_separator(
    block_id: str, width: int, height: int = BLOCK_SEPARATOR_HEIGHT
) -> Image.Image:
    """
    Создать разделитель с белым текстом block_id на черном фоне.
    Высота 60px, шрифт 36px, выравнивание по левому краю.
    Формат: BLOCK: XXXX-XXXX-XXX (OCR-устойчивый код)
    """
    from PIL import ImageFont

    from rd_core.models.armor_id import encode_block_id

    separator = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(separator)

    armor_code = encode_block_id(block_id)
    text = f"BLOCK: {armor_code}"

    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype("DejaVuSansMono.ttf", 36)
        except (IOError, OSError):
            font = ImageFont.load_default(size=36)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_height = bbox[3] - bbox[1]

    x = 50
    y = (height - text_height) // 2

    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    return separator


def merge_crops_vertically(
    crops: List[Image.Image], gap: int = 20, block_ids: Optional[List[str]] = None
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
        total_height = (
            sum(c.height for c in crops)
            + separator_height * separator_count
            + gap * (len(crops) - separator_count)
        )
    else:
        total_height = sum(c.height for c in crops) + gap * (len(crops) - 1)

    merged = Image.new("RGB", (max_width, total_height), (255, 255, 255))
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
        if crop.mode in ("RGBA", "LA"):
            crop = crop.convert("RGB")
        merged.paste(crop, (x_offset, y_offset))
        y_offset += crop.height

    return merged


def get_page_dimensions_streaming(pdf_path: str) -> Dict[int, Tuple[int, int]]:
    """Получить размеры всех страниц без полного рендеринга"""
    dims = {}
    with StreamingPDFProcessor(pdf_path) as processor:
        for i in range(processor.page_count):
            d = processor.get_page_dimensions(i)
            if d:
                dims[i] = d
    return dims
