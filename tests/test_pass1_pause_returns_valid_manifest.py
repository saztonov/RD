"""Тест: pass1_prepare_crops при немедленной отмене возвращает валидный
TwoPassManifest с обязательными pdf_path/crops_dir.

Регрессия из лога 2026-04-28: при should_stop возвращался
TwoPassManifest(strips=[], image_blocks=[]) без pdf_path/crops_dir →
TypeError → задача падала в error при попытке поставить на паузу.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_blocks():
    """Создать минимальный список блоков для PASS1."""
    from rd_core.models import Block, BlockType, ShapeType
    from rd_core.models.enums import BlockSource

    return [
        Block.create(
            page_index=0,
            coords_px=(10, 10, 100, 100),
            page_width=595,
            page_height=842,
            block_type=BlockType.TEXT,
            source=BlockSource.USER,
            shape_type=ShapeType.RECTANGLE,
        ),
    ]


def test_pass1_returns_valid_manifest_on_immediate_stop(tmp_path):
    """should_stop=True сразу — должен вернуться TwoPassManifest с
    обязательными pdf_path/crops_dir, без TypeError."""
    from services.remote_ocr.server.manifest_models import TwoPassManifest
    from services.remote_ocr.server.pdf_twopass.pass1_crops import (
        pass1_prepare_crops,
    )

    pdf_path = str(tmp_path / "fake.pdf")
    crops_dir = str(tmp_path / "crops")

    # Создаём PDF-заглушку для StreamingPDFProcessor (pdf=1 страница)
    import fitz

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    # Останавливаемся на первой же проверке
    blocks = _make_blocks()
    manifest = pass1_prepare_crops(
        pdf_path,
        blocks,
        crops_dir,
        should_stop=lambda: True,
    )

    assert isinstance(manifest, TwoPassManifest)
    assert manifest.pdf_path == pdf_path
    assert manifest.crops_dir == crops_dir
    assert manifest.strips == []
    assert manifest.image_blocks == []
