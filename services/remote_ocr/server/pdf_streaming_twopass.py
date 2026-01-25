"""
Двухпроходный алгоритм OCR с минимальным потреблением памяти.

ПРИМЕЧАНИЕ: Этот модуль перенесён в services/remote_ocr/server/pdf_twopass/ пакет.
Импорты сохранены для обратной совместимости.

PASS 1: Подготовка кропов → сохранение на диск
PASS 2: OCR с загрузкой по одному кропу с диска
"""
from __future__ import annotations

from .pdf_twopass import (
    cleanup_manifest_files,
    pass1_prepare_crops,
    pass2_ocr_from_manifest,
)

__all__ = [
    "pass1_prepare_crops",
    "pass2_ocr_from_manifest",
    "cleanup_manifest_files",
]
