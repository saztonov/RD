"""
Streaming PDF processing with PyMuPDF (fitz).

Memory optimization: pages are processed one by one and released immediately.
"""
from __future__ import annotations

import gc
import logging
import os
from typing import Dict, List, Optional, Tuple

import fitz
from PIL import Image, ImageDraw

from rd_pipeline.utils.memory import get_pil_image_size_mb
from rd_pipeline.processing.config import ProcessingConfig, default_config

logger = logging.getLogger(__name__)

# Default constants (can be overridden via config)
BLOCK_SEPARATOR_HEIGHT = 120

# Increase PIL limit
Image.MAX_IMAGE_PIXELS = 500_000_000

# Path to bundled font
_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
BUNDLED_FONT_PATH = os.path.join(_FONT_DIR, "DejaVuSansMono.ttf")


class StreamingPDFProcessor:
    """
    Streaming PDF processor with memory optimization.
    Processes pages sequentially, releasing memory after each.
    """

    def __init__(
        self,
        pdf_path: str,
        zoom: Optional[float] = None,
        config: Optional[ProcessingConfig] = None,
    ):
        self.pdf_path = pdf_path
        self.config = config or default_config
        self.zoom = zoom if zoom is not None else self.config.pdf_render_zoom
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
        """Release current page image."""
        if self._current_page_image:
            self._current_page_image.close()
            self._current_page_image = None
            self._current_page_idx = -1

    def _get_effective_zoom(self, page: fitz.Page) -> float:
        """Calculate zoom considering pixel limit."""
        rect = page.rect
        max_pixels = self.config.max_image_pixels
        estimated = (rect.width * self.zoom) * (rect.height * self.zoom)
        if estimated > max_pixels:
            return (max_pixels / (rect.width * rect.height)) ** 0.5
        return self.zoom

    def get_page_image(self, page_idx: int) -> Optional[Image.Image]:
        """
        Get page image (lazy loading).
        Caches current page, releases previous.
        """
        if page_idx == self._current_page_idx and self._current_page_image:
            return self._current_page_image

        self._release_page_image()

        if not self._doc or page_idx < 0 or page_idx >= len(self._doc):
            return None

        try:
            page = self._doc[page_idx]
            effective_zoom = self._get_effective_zoom(page)
            mat = fitz.Matrix(effective_zoom, effective_zoom)

            pix = page.get_pixmap(matrix=mat)

            if pix.alpha:
                mode = "RGBA"
            else:
                mode = "RGB"

            self._current_page_image = Image.frombytes(
                mode, (pix.width, pix.height), pix.samples
            )
            self._current_page_idx = page_idx

            page_mb = get_pil_image_size_mb(self._current_page_image)
            logger.info(
                f"Page {page_idx} rendered: {pix.width}x{pix.height} (~{page_mb:.1f} MB, zoom={effective_zoom:.2f})"
            )

            pix = None

            return self._current_page_image

        except Exception as e:
            logger.error(f"Error rendering page {page_idx}: {e}")
            return None

    def get_page_dimensions(self, page_idx: int) -> Optional[Tuple[int, int]]:
        """Get page dimensions."""
        if not self._doc or page_idx < 0 or page_idx >= len(self._doc):
            return None
        page = self._doc[page_idx]
        rect = page.rect
        zoom = self._get_effective_zoom(page)
        return (int(rect.width * zoom), int(rect.height * zoom))

    def crop_block_image(self, block, padding: int = 5) -> Optional[Image.Image]:
        """Crop block from current page."""
        page_image = self.get_page_image(block.page_index)
        if not page_image:
            return None

        from rd_domain.models import ShapeType

        nx1, ny1, nx2, ny2 = block.coords_norm
        img_w, img_h = page_image.width, page_image.height

        x1, y1 = int(nx1 * img_w), int(ny1 * img_h)
        x2, y2 = int(nx2 * img_w), int(ny2 * img_h)

        x1, y1 = max(0, x1 - padding), max(0, y1 - padding)
        x2, y2 = min(img_w, x2 + padding), min(img_h, y2 + padding)

        if block.shape_type == ShapeType.RECTANGLE or not block.polygon_points:
            return page_image.crop((x1, y1, x2, y2)).copy()

        # Polygon with mask
        crop_w, crop_h = x2 - x1, y2 - y1
        orig_x1, orig_y1, orig_x2, orig_y2 = block.coords_px
        bbox_w, bbox_h = orig_x2 - orig_x1, orig_y2 - orig_y1

        adjusted_points = []
        for px, py in block.polygon_points:
            norm_px = (px - orig_x1) / bbox_w if bbox_w else 0
            norm_py = (py - orig_y1) / bbox_h if bbox_h else 0
            adjusted_points.append((norm_px * crop_w, norm_py * crop_h))

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
        """Crop block as PDF."""
        if not self._doc:
            return None

        from rd_domain.models import ShapeType

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
            new_page.show_pdf_page(
                new_page.rect,
                self._doc,
                block.page_index,
                clip=clip_rect,
                rotate=-rotation,
            )

            if block.shape_type == ShapeType.POLYGON and block.polygon_points:
                orig_x1, orig_y1, orig_x2, orig_y2 = block.coords_px
                bbox_w, bbox_h = orig_x2 - orig_x1, orig_y2 - orig_y1

                polygon_pts = []
                for px, py in block.polygon_points:
                    norm_px = (px - orig_x1) / bbox_w if bbox_w else 0
                    norm_py = (py - orig_y1) / bbox_h if bbox_h else 0
                    polygon_pts.append(
                        fitz.Point(norm_px * crop_width, norm_py * crop_height)
                    )

                shape = new_page.new_shape()
                shape.draw_rect(new_page.rect)
                if polygon_pts:
                    shape.draw_polyline(polygon_pts + [polygon_pts[0]])
                shape.finish(color=None, fill=(1, 1, 1), even_odd=True)
                shape.commit()

            new_doc.save(output_path, deflate=True, garbage=4, clean=True)
            new_doc.close()

            return output_path

        except Exception as e:
            logger.error(f"PDF crop error {block.id}: {e}")
            return None


def split_large_crop(
    crop: Image.Image,
    max_height: Optional[int] = None,
    overlap: int = 100,
    config: Optional[ProcessingConfig] = None,
) -> List[Image.Image]:
    """Split large crop into parts."""
    cfg = config or default_config
    max_h = max_height if max_height is not None else cfg.max_single_block_height

    if crop.height <= max_h:
        return [crop]

    parts = []
    y = 0
    step = max_h - overlap

    while y < crop.height:
        y_end = min(y + max_h, crop.height)
        parts.append(crop.crop((0, y, crop.width, y_end)).copy())
        y += step
        if crop.height - y < overlap:
            break

    return parts


def create_block_separator(
    block_id: str,
    width: int,
    height: int = BLOCK_SEPARATOR_HEIGHT,
) -> Image.Image:
    """
    Create separator with white text block_id on black background.
    Format: BLOCK: XXXX-XXXX-XXX (OCR-resistant code)
    """
    from PIL import ImageFont
    from rd_domain.ids import encode_block_id

    separator = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(separator)

    armor_code = encode_block_id(block_id)
    text = f"BLOCK: {armor_code}"

    try:
        font = ImageFont.truetype("arial.ttf", 72)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype(BUNDLED_FONT_PATH, 72)
        except (IOError, OSError):
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_height = bbox[3] - bbox[1]

    x = 80
    y = (height - text_height) // 2

    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    return separator


def merge_crops_vertically(
    crops: List[Image.Image],
    gap: int = 20,
    block_ids: Optional[List[str]] = None,
    separator_height: int = BLOCK_SEPARATOR_HEIGHT,
) -> Image.Image:
    """
    Merge crops vertically with optional block_id separators.
    Separator is inserted only when block_id changes.
    """
    if not crops:
        raise ValueError("Empty crops list")

    use_separators = block_ids is not None and len(block_ids) == len(crops)
    max_width = max(c.width for c in crops)

    if use_separators:
        separator_count = 0
        prev_id = None
        for bid in block_ids:
            if bid != prev_id:
                separator_count += 1
                prev_id = bid
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
                separator = create_block_separator(current_block_id, max_width, separator_height)
                merged.paste(separator, (0, y_offset))
                y_offset += separator.height
                prev_block_id = current_block_id
            elif i > 0:
                y_offset += gap
        elif i > 0:
            y_offset += gap

        x_offset = 0
        if crop.mode in ("RGBA", "LA"):
            crop = crop.convert("RGB")
        merged.paste(crop, (x_offset, y_offset))
        y_offset += crop.height

    return merged


def get_page_dimensions_streaming(pdf_path: str) -> Dict[int, Tuple[int, int]]:
    """Get all page dimensions without full rendering."""
    dims = {}
    with StreamingPDFProcessor(pdf_path) as processor:
        for i in range(processor.page_count):
            d = processor.get_page_dimensions(i)
            if d:
                dims[i] = d
    return dims


def calculate_adaptive_dpi(
    clip_width_pt: float,
    clip_height_pt: float,
    target_dpi: int = 300,
    max_dimension: int = 4000,
    min_dpi: int = 150,
) -> Tuple[int, int, int]:
    """
    Calculate adaptive DPI to limit output image size.

    Args:
        clip_width_pt: Clip width in PDF points
        clip_height_pt: Clip height in PDF points
        target_dpi: Target DPI (default 300)
        max_dimension: Max size on longest side in pixels
        min_dpi: Minimum DPI (to preserve small text)

    Returns:
        (effective_dpi, output_width, output_height)
    """
    scale = target_dpi / 72.0
    width_px = int(clip_width_pt * scale)
    height_px = int(clip_height_pt * scale)

    max_side = max(width_px, height_px)
    if max_side <= max_dimension:
        return target_dpi, width_px, height_px

    scale_factor = max_dimension / max_side
    effective_dpi = max(min_dpi, int(target_dpi * scale_factor))

    new_scale = effective_dpi / 72.0
    output_width = int(clip_width_pt * new_scale)
    output_height = int(clip_height_pt * new_scale)

    return effective_dpi, output_width, output_height


def apply_ocr_preprocessing(
    img: Image.Image,
    contrast: float = 1.3,
    to_grayscale: bool = True,
) -> Image.Image:
    """
    Apply OCR preprocessing to image.

    Args:
        img: Source image (PIL.Image)
        contrast: Contrast enhancement factor (1.0 = no change)
        to_grayscale: Convert to grayscale

    Returns:
        Processed image
    """
    from PIL import ImageEnhance

    result = img

    if to_grayscale and img.mode != "L":
        result = img.convert("L")

    if contrast != 1.0:
        enhancer = ImageEnhance.Contrast(result)
        result = enhancer.enhance(contrast)

    return result


def render_block_crop(
    pdf_path: str,
    page_index: int,
    coords_norm: Tuple[float, float, float, float],
    target_dpi: int = 300,
    max_dimension: int = 4000,
    min_dpi: int = 150,
    padding_pt: float = 2.0,
    ocr_prep: Optional[str] = None,
    ocr_prep_contrast: float = 1.3,
    polygon_points: Optional[List[Tuple[float, float]]] = None,
    polygon_coords_px: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[Image.Image]:
    """
    Render block crop directly via clip (without full page rendering).

    Args:
        pdf_path: Path to PDF file
        page_index: Page index (0-based)
        coords_norm: Normalized coordinates (x1, y1, x2, y2) in 0..1 range
        target_dpi: Target DPI (will be reduced if crop exceeds max_dimension)
        max_dimension: Max pixel size on longest side
        min_dpi: Minimum DPI (to preserve small text)
        padding_pt: Padding in PDF points
        ocr_prep: OCR preprocessing mode ("text", "table") or None
        ocr_prep_contrast: Contrast coefficient for OCR-prep
        polygon_points: Polygon points for mask (normalized to bbox)
        polygon_coords_px: Original pixel coordinates of polygon

    Returns:
        PIL.Image.Image crop or None on error
    """
    try:
        doc = fitz.open(pdf_path)
        if page_index < 0 or page_index >= len(doc):
            doc.close()
            return None

        page = doc[page_index]
        rect = page.rect
        rotation = page.rotation

        nx1, ny1, nx2, ny2 = coords_norm

        x1_pt = max(rect.x0, rect.x0 + nx1 * rect.width - padding_pt)
        y1_pt = max(rect.y0, rect.y0 + ny1 * rect.height - padding_pt)
        x2_pt = min(rect.x1, rect.x0 + nx2 * rect.width + padding_pt)
        y2_pt = min(rect.y1, rect.y0 + ny2 * rect.height + padding_pt)

        clip_rect = fitz.Rect(x1_pt, y1_pt, x2_pt, y2_pt)

        if rotation != 0:
            clip_rect = clip_rect * page.derotation_matrix
            clip_rect.normalize()

        clip_width_pt = clip_rect.width
        clip_height_pt = clip_rect.height

        effective_dpi, output_width, output_height = calculate_adaptive_dpi(
            clip_width_pt, clip_height_pt, target_dpi, max_dimension, min_dpi
        )

        if effective_dpi != target_dpi:
            logger.info(
                f"Adaptive DPI: {target_dpi} -> {effective_dpi} "
                f"(clip {clip_width_pt:.0f}x{clip_height_pt:.0f}pt -> {output_width}x{output_height}px)"
            )

        zoom = effective_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        if rotation != 0:
            mat = mat * page.derotation_matrix

        pix = page.get_pixmap(matrix=mat, clip=clip_rect)

        if pix.alpha:
            mode = "RGBA"
        else:
            mode = "RGB"

        img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        pix = None
        doc.close()

        if polygon_points and polygon_coords_px:
            img = _apply_polygon_mask_to_crop(
                img, polygon_points, polygon_coords_px, (img.width, img.height)
            )

        if ocr_prep in ("text", "table"):
            img = apply_ocr_preprocessing(
                img, contrast=ocr_prep_contrast, to_grayscale=True
            )

        return img

    except Exception as e:
        logger.error(f"render_block_crop error: {e}")
        return None


def _apply_polygon_mask_to_crop(
    img: Image.Image,
    polygon_points: List[Tuple[float, float]],
    polygon_coords_px: Tuple[int, int, int, int],
    crop_size: Tuple[int, int],
) -> Image.Image:
    """
    Apply polygon mask to crop, filling area outside polygon with white.

    Args:
        img: Source image
        polygon_points: Polygon points in original pixel coordinates
        polygon_coords_px: Bounding box of polygon (x1, y1, x2, y2)
        crop_size: Crop size (width, height)

    Returns:
        Image with mask
    """
    orig_x1, orig_y1, orig_x2, orig_y2 = polygon_coords_px
    bbox_w = orig_x2 - orig_x1
    bbox_h = orig_y2 - orig_y1
    crop_w, crop_h = crop_size

    if bbox_w == 0 or bbox_h == 0:
        return img

    adjusted_points = []
    for px, py in polygon_points:
        norm_px = (px - orig_x1) / bbox_w
        norm_py = (py - orig_y1) / bbox_h
        adjusted_points.append((norm_px * crop_w, norm_py * crop_h))

    mask = Image.new("L", (crop_w, crop_h), 0)
    ImageDraw.Draw(mask).polygon(adjusted_points, fill=255)

    if img.mode == "L":
        result = Image.new("L", (crop_w, crop_h), 255)
    else:
        if img.mode == "RGBA":
            img = img.convert("RGB")
        result = Image.new("RGB", (crop_w, crop_h), (255, 255, 255))

    result.paste(img, mask=mask)
    mask.close()

    return result
