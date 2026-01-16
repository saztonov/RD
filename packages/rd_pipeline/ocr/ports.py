"""Base interface for OCR engines."""

from pathlib import Path
from typing import Optional, Protocol, Union

from PIL import Image


class OCRBackend(Protocol):
    """
    Interface for OCR engines.
    """

    def recognize(
        self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None
    ) -> str:
        """
        Recognize text in image.

        Args:
            image: image for recognition
            prompt: dict with keys 'system' and 'user' (optional)
            json_mode: force JSON output mode

        Returns:
            Recognized text
        """
        ...

    def supports_native_pdf(self) -> bool:
        """
        Check if backend supports direct PDF input.

        Returns:
            True if recognize_pdf() is available, otherwise False
        """
        return False

    def recognize_pdf(
        self,
        pdf_path: Union[str, Path],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
    ) -> str:
        """
        Recognize text directly from PDF file (optional).

        Args:
            pdf_path: path to PDF file
            prompt: dict with keys 'system' and 'user' (optional)
            json_mode: force JSON output mode

        Returns:
            Recognized text

        Raises:
            NotImplementedError: if backend doesn't support native PDF
        """
        raise NotImplementedError("This backend doesn't support direct PDF input")
