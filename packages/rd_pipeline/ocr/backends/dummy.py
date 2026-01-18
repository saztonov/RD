"""Dummy OCR Backend (placeholder)."""

from typing import Optional

from PIL import Image


class DummyOCRBackend:
    """OCR placeholder."""

    def recognize(
        self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None,
        timeout_multiplier: int = 1
    ) -> str:
        return "[OCR placeholder - OCR engine not configured]"
