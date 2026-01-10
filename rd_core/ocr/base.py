"""Базовый интерфейс для OCR движков"""
from pathlib import Path
from typing import Optional, Protocol, Union

from PIL import Image


class OCRBackend(Protocol):
    """
    Интерфейс для OCR-движков
    """

    def recognize(
        self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None
    ) -> str:
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

    def supports_native_pdf(self) -> bool:
        """
        Проверить, поддерживает ли backend прямой ввод PDF.

        Returns:
            True если recognize_pdf() доступен, иначе False
        """
        return False

    def recognize_pdf(
        self,
        pdf_path: Union[str, Path],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
    ) -> str:
        """
        Распознать текст напрямую из PDF файла (опционально).

        Args:
            pdf_path: путь к PDF файлу
            prompt: dict с ключами 'system' и 'user' (опционально)
            json_mode: принудительный JSON режим вывода

        Returns:
            Распознанный текст

        Raises:
            NotImplementedError: если backend не поддерживает native PDF
        """
        raise NotImplementedError("Этот backend не поддерживает прямой ввод PDF")
