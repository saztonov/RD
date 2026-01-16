"""Image preprocessing for OCR based on block type.

Different block types benefit from different preprocessing:
- TEXT: grayscale + high contrast + sharpen (clean text extraction)
- TABLE: grayscale + moderate contrast (preserve structure)
- IMAGE: minimal processing (preserve details and colors)
- STAMP: grayscale + denoise (often has noise/artifacts)
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


class PreprocessMode(Enum):
    """Preprocessing modes for different block types."""

    NONE = "none"  # No preprocessing
    TEXT = "text"  # Grayscale + high contrast + sharpen
    TABLE = "table"  # Grayscale + moderate contrast
    IMAGE = "image"  # Minimal (preserve colors)
    STAMP = "stamp"  # Grayscale + denoise


def get_preprocess_mode_for_block(block) -> PreprocessMode:
    """
    Determine preprocessing mode based on block type and category.

    Args:
        block: Block object with block_type and optional category_code

    Returns:
        PreprocessMode enum value
    """
    from rd_domain.models import BlockType

    block_type = block.block_type

    if block_type == BlockType.TEXT:
        return PreprocessMode.TEXT
    elif block_type == BlockType.TABLE:
        return PreprocessMode.TABLE
    elif block_type == BlockType.IMAGE:
        # Check for stamp category
        category_code = getattr(block, "category_code", None)
        if category_code == "stamp":
            return PreprocessMode.STAMP
        return PreprocessMode.IMAGE
    else:
        return PreprocessMode.NONE


def preprocess_crop(
    image: Image.Image,
    mode: PreprocessMode,
    contrast: float = 1.3,
    sharpen_strength: float = 1.0,
) -> Image.Image:
    """
    Apply preprocessing to crop image based on mode.

    Args:
        image: PIL Image to process
        mode: PreprocessMode determining what processing to apply
        contrast: Contrast enhancement factor (1.0 = no change)
        sharpen_strength: Sharpening strength (0.0-2.0, 1.0 = default)

    Returns:
        Processed PIL Image
    """
    if mode == PreprocessMode.NONE:
        return image

    if mode == PreprocessMode.TEXT:
        return _preprocess_text(image, contrast, sharpen_strength)
    elif mode == PreprocessMode.TABLE:
        return _preprocess_table(image, contrast)
    elif mode == PreprocessMode.STAMP:
        return _preprocess_stamp(image)
    elif mode == PreprocessMode.IMAGE:
        return _preprocess_image(image)
    else:
        return image


def _preprocess_text(
    image: Image.Image, contrast: float = 1.3, sharpen_strength: float = 1.0
) -> Image.Image:
    """
    Preprocess image for text OCR.

    - Convert to grayscale
    - Auto-contrast (normalize levels)
    - Enhance contrast
    - Sharpen (improves character edges)
    """
    # Convert to grayscale
    if image.mode != "L":
        result = ImageOps.grayscale(image)
    else:
        result = image.copy()

    # Auto-contrast: normalize levels (cutoff removes extreme 1%)
    result = ImageOps.autocontrast(result, cutoff=1)

    # Enhance contrast
    if contrast != 1.0:
        enhancer = ImageEnhance.Contrast(result)
        result = enhancer.enhance(contrast)

    # Sharpen for cleaner character edges
    if sharpen_strength > 0:
        if sharpen_strength <= 1.0:
            result = result.filter(ImageFilter.SHARPEN)
        else:
            # Apply multiple times for stronger effect
            for _ in range(int(sharpen_strength)):
                result = result.filter(ImageFilter.SHARPEN)

    return result


def _preprocess_table(image: Image.Image, contrast: float = 1.2) -> Image.Image:
    """
    Preprocess image for table OCR.

    - Convert to grayscale
    - Auto-contrast (gentler)
    - Moderate contrast enhancement
    - No sharpening (preserve line structure)
    """
    # Convert to grayscale
    if image.mode != "L":
        result = ImageOps.grayscale(image)
    else:
        result = image.copy()

    # Auto-contrast with gentler cutoff (preserve more detail)
    result = ImageOps.autocontrast(result, cutoff=2)

    # Moderate contrast
    if contrast != 1.0:
        enhancer = ImageEnhance.Contrast(result)
        result = enhancer.enhance(contrast)

    return result


def _preprocess_stamp(image: Image.Image) -> Image.Image:
    """
    Preprocess image for stamp recognition.

    - Convert to grayscale
    - Median filter for noise reduction (stamps often have artifacts)
    - Light contrast enhancement
    """
    # Convert to grayscale
    if image.mode != "L":
        result = ImageOps.grayscale(image)
    else:
        result = image.copy()

    # Median filter removes noise while preserving edges
    # Size 3 is gentle, won't blur text too much
    result = result.filter(ImageFilter.MedianFilter(size=3))

    # Light auto-contrast
    result = ImageOps.autocontrast(result, cutoff=3)

    return result


def _preprocess_image(image: Image.Image) -> Image.Image:
    """
    Minimal preprocessing for image blocks.

    - Keep colors (don't convert to grayscale)
    - Very light contrast enhancement only
    """
    # Keep in RGB/RGBA mode
    result = image.copy()

    # Very gentle contrast boost (if image is washed out)
    enhancer = ImageEnhance.Contrast(result)
    result = enhancer.enhance(1.05)

    return result


def preprocess_for_ocr(
    image: Image.Image,
    block_type_str: str,
    category_code: Optional[str] = None,
    enabled: bool = True,
    contrast: float = 1.3,
) -> Image.Image:
    """
    Convenience function to preprocess image based on block type string.

    Args:
        image: PIL Image
        block_type_str: Block type as string ("text", "table", "image")
        category_code: Optional category code (e.g., "stamp")
        enabled: Whether preprocessing is enabled
        contrast: Contrast enhancement factor

    Returns:
        Processed image
    """
    if not enabled:
        return image

    # Map string to PreprocessMode
    block_type_lower = block_type_str.lower()

    if block_type_lower == "text":
        mode = PreprocessMode.TEXT
    elif block_type_lower == "table":
        mode = PreprocessMode.TABLE
    elif block_type_lower == "image":
        if category_code == "stamp":
            mode = PreprocessMode.STAMP
        else:
            mode = PreprocessMode.IMAGE
    else:
        mode = PreprocessMode.NONE

    return preprocess_crop(image, mode, contrast=contrast)
