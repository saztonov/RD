"""Обратная совместимость: реэкспорт OcrPreviewWidget из ocr_preview/."""
from app.gui.ocr_preview import OcrPreviewWidget  # noqa: F401

__all__ = ["OcrPreviewWidget"]
