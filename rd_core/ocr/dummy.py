"""Dummy OCR Backend (заглушка)"""
from typing import Optional
from PIL import Image


class DummyOCRBackend:
    """Заглушка для OCR"""
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None) -> str:
        return "[OCR placeholder - OCR engine not configured]"


