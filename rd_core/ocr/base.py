"""Базовый интерфейс для OCR движков"""
from typing import Protocol, Optional
from PIL import Image


class OCRBackend(Protocol):
    """
    Интерфейс для OCR-движков
    """
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None) -> str:
        """
        Распознать текст на изображении
        
        Args:
            image: изображение для распознавания
            prompt: dict с ключами 'system' и 'user' (опционально)
            json_mode: принудительный JSON режим вывода
        
        Returns:
            Распознанный текст
        """
        ...


