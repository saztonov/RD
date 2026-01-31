"""Async Dummy OCR Backend (заглушка)"""
from typing import Optional

from PIL import Image


class AsyncDummyOCRBackend:
    """Асинхронная заглушка для OCR"""

    def supports_pdf_input(self) -> bool:
        """Заглушка не поддерживает PDF"""
        return False

    async def recognize_async(
        self,
        image: Optional[Image.Image],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        pdf_file_path: Optional[str] = None,
    ) -> str:
        return "[OCR placeholder - async OCR engine not configured]"

    async def close(self):
        """Заглушка для закрытия клиента"""
        pass
