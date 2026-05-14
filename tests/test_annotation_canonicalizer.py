"""Тесты для rd_core/annotation_canonicalizer — синхронизация геометрии блоков."""

from rd_core.annotation_canonicalizer import (
    canonicalize_annotation_document,
    sync_block_to_page,
)
from rd_core.models import (
    Block,
    BlockSource,
    BlockType,
    Document,
    Page,
    ShapeType,
)


def _make_doc(page_width: int, page_height: int, blocks: list[Block]) -> Document:
    return Document(
        pdf_path="dummy.pdf",
        pages=[
            Page(page_number=0, width=page_width, height=page_height, blocks=blocks)
        ],
    )


def _make_polygon(
    points: list[tuple[int, int]],
    page_width: int,
    page_height: int,
    *,
    coords_px: tuple[int, int, int, int] | None = None,
) -> Block:
    if coords_px is None:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        coords_px = (min(xs), min(ys), max(xs), max(ys))
    return Block.create(
        page_index=0,
        coords_px=coords_px,
        page_width=page_width,
        page_height=page_height,
        block_type=BlockType.TEXT,
        source=BlockSource.USER,
        shape_type=ShapeType.POLYGON,
        polygon_points=points,
    )


class TestCanonicalizePolygons:
    def test_legacy_polygon_scaled_by_page(self):
        """Polygon без polygon_points_norm масштабируется через полные размеры страницы."""
        points = [(100, 100), (400, 150), (350, 400), (200, 380)]
        block = _make_polygon(points, page_width=1000, page_height=1500)
        block.polygon_points_norm = None  # имитируем legacy

        doc = _make_doc(1000, 1500, [block])
        canonicalize_annotation_document(
            doc, pdf_path="dummy.pdf", pdf_page_sizes=[(1240, 1754)]
        )

        expected = [
            (int(round(px / 1000 * 1240)), int(round(py / 1500 * 1754)))
            for px, py in points
        ]
        assert block.polygon_points == expected
        assert block.polygon_points_norm is not None

    def test_norm_polygon_restored_without_bbox_drift(self):
        """Polygon с polygon_points_norm восстанавливается строго через нормализованные вершины."""
        points = [(100, 100), (400, 150), (350, 400), (200, 380)]
        block = _make_polygon(points, page_width=1000, page_height=1500)
        # Имитируем сценарий: bbox в JSON слегка "испорчен" округлениями.
        block.coords_px = (99, 99, 401, 401)
        block.coords_norm = (0.099, 0.066, 0.401, 0.2673)

        doc = _make_doc(1000, 1500, [block])
        canonicalize_annotation_document(
            doc, pdf_path="dummy.pdf", pdf_page_sizes=[(1240, 1754)]
        )

        expected = [
            (int(round(nx * 1240)), int(round(ny * 1754)))
            for nx, ny in block.polygon_points_norm
        ]
        assert block.polygon_points == expected

    def test_bbox_recomputed_from_polygon(self):
        """coords_px/coords_norm после канонизации согласованы с вершинами полигона."""
        points = [(100, 100), (400, 150), (350, 400), (200, 380)]
        block = _make_polygon(points, page_width=1000, page_height=1500)
        # Намеренно ставим неверный bbox.
        block.coords_px = (0, 0, 1, 1)
        block.coords_norm = (0.0, 0.0, 0.001, 0.001)

        doc = _make_doc(1000, 1500, [block])
        canonicalize_annotation_document(
            doc, pdf_path="dummy.pdf", pdf_page_sizes=[(1240, 1754)]
        )

        xs = [p[0] for p in block.polygon_points]
        ys = [p[1] for p in block.polygon_points]
        assert block.coords_px == (min(xs), min(ys), max(xs), max(ys))

    def test_same_size_identity(self):
        """При совпадающих размерах страницы вершины не меняются."""
        points = [(100, 100), (400, 150), (350, 400), (200, 380)]
        block = _make_polygon(points, page_width=1000, page_height=1500)

        doc = _make_doc(1000, 1500, [block])
        canonicalize_annotation_document(
            doc, pdf_path="dummy.pdf", pdf_page_sizes=[(1000, 1500)]
        )

        assert block.polygon_points == points

    def test_prefer_coords_px_scales_polygon(self):
        """prefer_coords_px=True тоже корректно масштабирует полигон через нормализованные вершины."""
        points = [(100, 100), (400, 150), (350, 400), (200, 380)]
        block = _make_polygon(points, page_width=1000, page_height=1500)

        doc = _make_doc(1000, 1500, [block])
        canonicalize_annotation_document(
            doc,
            pdf_path="dummy.pdf",
            pdf_page_sizes=[(1240, 1754)],
            prefer_coords_px=True,
        )

        expected = [
            (int(round(nx * 1240)), int(round(ny * 1754)))
            for nx, ny in block.polygon_points_norm
        ]
        assert block.polygon_points == expected


class TestCanonicalizeRectangles:
    def test_rectangle_unchanged_at_same_size(self):
        block = Block.create(
            page_index=0,
            coords_px=(100, 200, 500, 400),
            page_width=1000,
            page_height=1500,
            block_type=BlockType.TEXT,
            source=BlockSource.USER,
        )
        doc = _make_doc(1000, 1500, [block])
        canonicalize_annotation_document(
            doc, pdf_path="dummy.pdf", pdf_page_sizes=[(1000, 1500)]
        )
        assert block.coords_px == (100, 200, 500, 400)

    def test_rectangle_scales_through_coords_norm(self):
        block = Block.create(
            page_index=0,
            coords_px=(100, 150, 500, 300),
            page_width=1000,
            page_height=1500,
            block_type=BlockType.TEXT,
            source=BlockSource.USER,
        )
        doc = _make_doc(1000, 1500, [block])
        canonicalize_annotation_document(
            doc, pdf_path="dummy.pdf", pdf_page_sizes=[(2000, 3000)]
        )
        assert block.coords_px == (200, 300, 1000, 600)


class TestSyncBlockToPage:
    def test_returns_change_flag(self):
        block = _make_polygon(
            [(100, 100), (400, 150), (350, 400)],
            page_width=1000,
            page_height=1500,
        )
        changed = sync_block_to_page(
            block,
            page_width=1240,
            page_height=1754,
            prefer_coords_px=False,
            old_page_width=1000,
            old_page_height=1500,
        )
        assert changed is True

    def test_no_change_when_size_matches(self):
        block = _make_polygon(
            [(100, 100), (400, 150), (350, 400)],
            page_width=1000,
            page_height=1500,
        )
        changed = sync_block_to_page(
            block,
            page_width=1000,
            page_height=1500,
            prefer_coords_px=False,
            old_page_width=1000,
            old_page_height=1500,
        )
        assert changed is False
