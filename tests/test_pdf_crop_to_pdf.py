"""Тесты PDF-кропа IMAGE-блоков.

Покрывают:
- rotation=90/270: PDF-кроп имеет визуально-корректные размеры (wide для wide блока)
- CAD-страница с cropbox.x0 != 0: кроп берётся из визуального центра (без сдвига влево)
- Polygon-маска: точки расположены внутри padded crop без перекоса
- Регрессия rotation=0, cropbox=mediabox: bbox совпадает с координатами клипа
"""
from __future__ import annotations

import fitz
import pytest

from rd_core.models import Block, BlockSource, BlockType, ShapeType
from services.remote_ocr.server.pdf_streaming_core import (
    StreamingPDFProcessor,
    _polygon_to_crop_points,
    _visual_clip_to_source_clip,
)


def _make_pdf(tmp_path, page_width, page_height, *, rotation=0, cropbox=None,
              draw_marker=False):
    """Создать минимальный PDF с одной страницей.

    Если draw_marker=True — рисует крупный чёрный прямоугольник в центре
    cropbox-а, чтобы можно было проверять контент кропа визуально.
    """
    doc = fitz.open()
    page = doc.new_page(width=page_width, height=page_height)
    if cropbox is not None:
        page.set_cropbox(cropbox)
    if draw_marker:
        cb = page.cropbox
        cx, cy = (cb.x0 + cb.x1) / 2, (cb.y0 + cb.y1) / 2
        marker = fitz.Rect(cx - 20, cy - 20, cx + 20, cy + 20)
        page.draw_rect(marker, color=(0, 0, 0), fill=(0, 0, 0))
    if rotation:
        page.set_rotation(rotation)
    pdf_path = str(tmp_path / "test.pdf")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _block(coords_norm, *, polygon_points=None, coords_px=None, page_index=0):
    """Сборка Block без вызова Block.create (там coords_norm пересчитывается)."""
    shape = ShapeType.POLYGON if polygon_points else ShapeType.RECTANGLE
    if coords_px is None:
        coords_px = (0, 0, 100, 100)
    return Block(
        id="TEST-BLOCK-001",
        page_index=page_index,
        coords_px=coords_px,
        coords_norm=coords_norm,
        block_type=BlockType.IMAGE,
        source=BlockSource.USER,
        shape_type=shape,
        polygon_points=polygon_points,
    )


# ---------------------------------------------------------------------------
# Unit-тесты helper-функций
# ---------------------------------------------------------------------------


def test_visual_clip_to_source_rotation_zero_no_cropbox_offset():
    """rotation=0, cropbox=(0,0,W,H): source == visual."""
    doc = fitz.open()
    doc.new_page(width=1000, height=500)
    page = doc[0]
    visual = fitz.Rect(100, 200, 600, 400)
    source = _visual_clip_to_source_clip(visual, page, page.cropbox)
    doc.close()
    assert source is not None
    assert abs(source.x0 - 100) < 0.5
    assert abs(source.y0 - 200) < 0.5
    assert abs(source.x1 - 600) < 0.5
    assert abs(source.y1 - 400) < 0.5


def test_visual_clip_to_source_rotation_zero_cad_cropbox_offset():
    """rotation=0, cropbox.x0=500: source сдвинут на cropbox.x0 относительно visual."""
    doc = fitz.open()
    doc.new_page(width=3000, height=4000)
    page = doc[0]
    page.set_cropbox(fitz.Rect(500, 0, 2500, 4000))  # cropbox шириной 2000, смещён на 500
    cropbox = page.cropbox
    # visual_clip от (200,1000) до (1800,3000) в page.rect-space (anchored at 0)
    visual = fitz.Rect(200, 1000, 1800, 3000)
    source = _visual_clip_to_source_clip(visual, page, cropbox)
    doc.close()
    assert source is not None
    # source должен начинаться с cropbox.x0 + 200 = 700, и т.д.
    assert abs(source.x0 - 700) < 0.5
    assert abs(source.y0 - 1000) < 0.5
    assert abs(source.x1 - 2300) < 0.5
    assert abs(source.y1 - 3000) < 0.5


def test_visual_clip_to_source_rotation_90():
    """rotation=90: visual_clip * derotation_matrix должен давать валидный rect."""
    doc = fitz.open()
    doc.new_page(width=1000, height=500)
    page = doc[0]
    page.set_rotation(90)
    # При rotation=90 page.rect=(0,0,500,1000) (W/H swapped)
    visual = fitz.Rect(50, 400, 450, 600)  # широкая горизонтальная область
    source = _visual_clip_to_source_clip(visual, page, page.cropbox)
    doc.close()
    assert source is not None
    # source должен быть валидным rect (width > 0, height > 0)
    assert source.width > 0
    assert source.height > 0
    # Все координаты конечны
    import math
    for v in (source.x0, source.y0, source.x1, source.y1):
        assert math.isfinite(v)


def test_polygon_to_crop_points_with_padding():
    """Полигон должен размещаться внутри padded crop, начиная с (pad_left, pad_top)."""
    # Bbox 100x100 (в client px) с polygon в углах
    coords_px = (10, 10, 110, 110)
    polygon_points = [(10, 10), (110, 10), (110, 110), (10, 110)]  # квадрат по bbox
    # Crop 120x120 в render px с padding 10 с каждой стороны → bbox 100x100 внутри
    pad_left, pad_top = 10, 10
    bbox_w_in_crop = 100
    bbox_h_in_crop = 100
    points = _polygon_to_crop_points(
        polygon_points, coords_px, pad_left, pad_top, bbox_w_in_crop, bbox_h_in_crop,
    )
    # Углы должны быть смещены на (10,10), (110,10), (110,110), (10,110) ВНУТРИ crop
    assert points[0] == (10, 10)
    assert points[1] == (110, 10)
    assert points[2] == (110, 110)
    assert points[3] == (10, 110)


# ---------------------------------------------------------------------------
# Integration-тесты crop_block_to_pdf
# ---------------------------------------------------------------------------


def test_rotated_page_wide_block_produces_wide_crop(tmp_path):
    """rotation=90: широкий по виду блок должен дать PDF-кроп с W > H."""
    # Исходная страница 1000x500, после set_rotation(90) визуально 500x1000.
    pdf_path = _make_pdf(tmp_path, 1000, 500, rotation=90)
    output_path = str(tmp_path / "out.pdf")

    # nx1=0.1, ny1=0.4, nx2=0.9, ny2=0.6 → визуально 0.8*500 x 0.2*1000 = 400 x 200
    block = _block((0.1, 0.4, 0.9, 0.6))

    with StreamingPDFProcessor(pdf_path) as p:
        result = p.crop_block_to_pdf(block, output_path, padding_pt=2)

    assert result == output_path
    out_doc = fitz.open(output_path)
    out_page = out_doc[0]
    out_w, out_h = out_page.rect.width, out_page.rect.height
    out_doc.close()

    assert out_w > out_h, f"Expected wide crop (w>h), got {out_w}x{out_h}"
    # ±5pt допуска (padding=2 → ожидаем ~404 x 204)
    assert abs(out_w - 404) < 5, f"Width mismatch: {out_w}"
    assert abs(out_h - 204) < 5, f"Height mismatch: {out_h}"


def test_cad_cropbox_offset_crop_not_shifted_left(tmp_path):
    """CAD-страница с cropbox.x0=500: маркер в центре визуальной области
    должен оказаться в центре crop, без сдвига влево.
    """
    cropbox = fitz.Rect(500, 0, 2500, 4000)
    pdf_path = _make_pdf(tmp_path, 3000, 4000, cropbox=cropbox, draw_marker=True)
    output_path = str(tmp_path / "out.pdf")

    # Блок 50% × 50% по центру визуального cropbox
    block = _block((0.25, 0.25, 0.75, 0.75))

    with StreamingPDFProcessor(pdf_path) as p:
        result = p.crop_block_to_pdf(block, output_path, padding_pt=2)

    assert result == output_path
    out_doc = fitz.open(output_path)
    out_page = out_doc[0]
    # Размер должен соответствовать визуальному bbox: 0.5 * 2000 x 0.5 * 4000 = 1000 x 2000
    assert abs(out_page.rect.width - 1004) < 5
    assert abs(out_page.rect.height - 2004) < 5

    # Маркер должен оказаться около центра crop (т.к. он был в центре визуальной области)
    pix = out_page.get_pixmap(matrix=fitz.Matrix(1, 1))
    img_w, img_h = pix.width, pix.height
    cx_px, cy_px = img_w // 2, img_h // 2
    # Берём центральный пиксель — должен быть тёмным (маркер)
    pixel = pix.pixel(cx_px, cy_px)
    out_doc.close()
    # Сэмпл — кортеж RGB; маркер чёрный → значения < 50
    assert max(pixel[:3]) < 80, f"Center pixel not dark: {pixel} (marker missing from center)"


def test_regression_normal_page_no_rotation(tmp_path):
    """Обычная A4-страница, rotation=0, cropbox=mediabox: размер crop = bbox * 100% page."""
    pdf_path = _make_pdf(tmp_path, 595, 842)
    output_path = str(tmp_path / "out.pdf")

    # Блок в центре: 0.2..0.8 по обоим осям → 357 x 505 + 2*pad = ~361 x ~509
    block = _block((0.2, 0.2, 0.8, 0.8))

    with StreamingPDFProcessor(pdf_path) as p:
        result = p.crop_block_to_pdf(block, output_path, padding_pt=2)

    assert result == output_path
    out_doc = fitz.open(output_path)
    out_page = out_doc[0]
    out_w, out_h = out_page.rect.width, out_page.rect.height
    out_doc.close()

    # bbox: 0.6 * 595 = 357, 0.6 * 842 = 505.2
    # + 4pt padding (2 с каждой стороны)
    assert abs(out_w - 361) < 5
    assert abs(out_h - 509) < 5


def test_polygon_block_writes_pdf_without_exceptions(tmp_path):
    """POLYGON IMAGE-блок: PDF-кроп должен создаваться без исключений."""
    pdf_path = _make_pdf(tmp_path, 1000, 1000)
    output_path = str(tmp_path / "out.pdf")

    # Треугольник внутри bbox 100..500 × 100..500 (client px), coords_norm 0.1..0.5
    polygon_points = [(100, 100), (500, 100), (300, 500)]
    coords_px = (100, 100, 500, 500)
    block = _block(
        (0.1, 0.1, 0.5, 0.5),
        polygon_points=polygon_points,
        coords_px=coords_px,
    )

    with StreamingPDFProcessor(pdf_path) as p:
        result = p.crop_block_to_pdf(block, output_path, padding_pt=10)

    assert result == output_path
    # PDF открывается и имеет одну страницу
    out_doc = fitz.open(output_path)
    assert out_doc.page_count == 1
    out_doc.close()
