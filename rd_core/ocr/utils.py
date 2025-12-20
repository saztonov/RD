"""Утилиты для работы с изображениями в OCR"""
import base64
import io
from PIL import Image


def image_to_base64(image: Image.Image, max_size: int = 1500) -> str:
    """
    Конвертировать PIL Image в base64 с опциональным ресайзом
    
    Args:
        image: PIL изображение
        max_size: максимальный размер стороны
    
    Returns:
        Base64 строка
    """
    if image.width > max_size or image.height > max_size:
        ratio = min(max_size / image.width, max_size / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        image = image.resize(new_size, Image.LANCZOS)
    
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def image_to_pdf_base64(image: Image.Image) -> str:
    """
    Конвертировать PIL Image в PDF base64 (векторное качество)
    
    Args:
        image: PIL изображение
    
    Returns:
        Base64 строка PDF
    """
    buffer = io.BytesIO()
    if image.mode == 'RGBA':
        rgb_image = Image.new('RGB', image.size, (255, 255, 255))
        rgb_image.paste(image, mask=image.split()[3])
        image = rgb_image
    elif image.mode != 'RGB':
        image = image.convert('RGB')
    
    image.save(buffer, format='PDF', resolution=300.0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

