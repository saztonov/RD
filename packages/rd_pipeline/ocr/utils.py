"""Utilities for image handling in OCR."""

import base64
import io

from PIL import Image


def image_to_base64(image: Image.Image, max_size: int = 1500) -> str:
    """
    Convert PIL Image to base64 with optional resize.

    Args:
        image: PIL image
        max_size: maximum side size

    Returns:
        Base64 string
    """
    if image.width > max_size or image.height > max_size:
        ratio = min(max_size / image.width, max_size / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        image = image.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def image_to_pdf_base64(image: Image.Image) -> str:
    """
    Convert PIL Image to PDF base64 (vector quality).

    Args:
        image: PIL image

    Returns:
        PDF base64 string
    """
    buffer = io.BytesIO()
    if image.mode == "RGBA":
        rgb_image = Image.new("RGB", image.size, (255, 255, 255))
        rgb_image.paste(image, mask=image.split()[3])
        image = rgb_image
    elif image.mode != "RGB":
        image = image.convert("RGB")

    image.save(buffer, format="PDF", resolution=300.0)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def pdf_file_to_base64(path: str) -> str:
    """
    Read PDF file and return base64 string.

    Args:
        path: Path to PDF file

    Returns:
        Base64 string of PDF content

    Raises:
        FileNotFoundError: if file doesn't exist
        IOError: if file cannot be read
    """
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")
