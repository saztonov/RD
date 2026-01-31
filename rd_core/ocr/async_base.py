"""Базовый интерфейс для асинхронных OCR движков"""
from typing import Optional, Protocol, runtime_checkable

from PIL import Image


@runtime_checkable
class AsyncOCRBackend(Protocol):
    """
    Асинхронный интерфейс для OCR-движков.

    Обеспечивает неблокирующую обработку OCR запросов через asyncio,
    что позволяет эффективно использовать I/O-bound операции.
    """

    async def recognize_async(
        self,
        image: Optional[Image.Image],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        pdf_file_path: Optional[str] = None,
    ) -> str:
        """
        Асинхронно распознать текст на изображении или PDF

        Args:
            image: изображение для распознавания (опционально если передан pdf_file_path)
            prompt: dict с ключами 'system' и 'user' (опционально)
            json_mode: принудительный JSON режим вывода
            pdf_file_path: путь к PDF файлу для моделей с поддержкой PDF

        Returns:
            Распознанный текст
        """
        ...

    def supports_pdf_input(self) -> bool:
        """
        Проверяет, поддерживает ли бэкенд прямой ввод PDF файлов

        Returns:
            True если поддерживает PDF, False иначе
        """
        ...
