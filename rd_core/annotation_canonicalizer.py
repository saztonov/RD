"""Helpers for canonicalizing annotations against the currently opened PDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rd_core.models import Block, Document, Page, ShapeType
from rd_core.pdf_utils import PDFDocument, normalize_coords_norm


@dataclass
class AnnotationCompatibility:
    compatible: bool
    reason: str = ""


@dataclass
class AnnotationCanonicalizationResult:
    changed: bool
    strategy: str
    page_count: int


def get_pdf_preview_page_sizes(pdf_document: PDFDocument) -> list[tuple[int, int]]:
    """Return actual preview dimensions for all PDF pages."""
    sizes: list[tuple[int, int]] = []
    for page_index in range(pdf_document.page_count):
        dims = pdf_document.get_page_dimensions(page_index)
        if not dims:
            raise ValueError(
                f"Failed to determine preview size for page {page_index}"
            )
        sizes.append((int(dims[0]), int(dims[1])))
    return sizes


def check_annotation_compatibility(
    document: Document,
    pdf_page_sizes: Iterable[tuple[int, int]],
    *,
    tolerance_px: int = 2,
) -> AnnotationCompatibility:
    """Check whether annotation page geometry matches the target PDF."""
    page_sizes = list(pdf_page_sizes)
    doc_pages = sorted(document.pages, key=lambda page: page.page_number)

    if len(doc_pages) != len(page_sizes):
        return AnnotationCompatibility(
            compatible=False,
            reason=(
                "Different page count: "
                f"annotation={len(doc_pages)}, pdf={len(page_sizes)}"
            ),
        )

    for index, ((pdf_width, pdf_height), page) in enumerate(zip(page_sizes, doc_pages)):
        if (
            abs(int(page.width) - int(pdf_width)) > tolerance_px
            or abs(int(page.height) - int(pdf_height)) > tolerance_px
        ):
            return AnnotationCompatibility(
                compatible=False,
                reason=(
                    f"Page {index + 1}: "
                    f"annotation={page.width}x{page.height}, "
                    f"pdf={pdf_width}x{pdf_height}"
                ),
            )

    return AnnotationCompatibility(compatible=True)


def canonicalize_annotation_document(
    document: Document,
    *,
    pdf_path: str,
    pdf_page_sizes: Iterable[tuple[int, int]],
    prefer_coords_px: bool = False,
) -> AnnotationCanonicalizationResult:
    """Align annotation page sizes and block coordinates with the target PDF."""
    page_sizes = list(pdf_page_sizes)
    strategy = "px" if prefer_coords_px else "norm"
    changed = document.pdf_path != pdf_path or len(document.pages) != len(page_sizes)

    pages_by_number = {page.page_number: page for page in document.pages}
    normalized_pages: list[Page] = []

    for page_number, (page_width, page_height) in enumerate(page_sizes):
        existing_page = pages_by_number.get(page_number)
        if existing_page is None:
            normalized_pages.append(
                Page(page_number=page_number, width=page_width, height=page_height)
            )
            changed = True
            continue

        old_page_width = int(existing_page.width) if existing_page.width else int(page_width)
        old_page_height = int(existing_page.height) if existing_page.height else int(page_height)

        changed = changed or (
            old_page_width != int(page_width)
            or old_page_height != int(page_height)
        )
        existing_page.width = int(page_width)
        existing_page.height = int(page_height)

        for block in existing_page.blocks:
            changed = (
                sync_block_to_page(
                    block,
                    page_width=int(page_width),
                    page_height=int(page_height),
                    prefer_coords_px=prefer_coords_px,
                    old_page_width=old_page_width,
                    old_page_height=old_page_height,
                )
                or changed
            )

        normalized_pages.append(existing_page)

    document.pages = normalized_pages
    document.pdf_path = pdf_path

    return AnnotationCanonicalizationResult(
        changed=changed,
        strategy=strategy,
        page_count=len(page_sizes),
    )


def sync_block_to_page(
    block: Block,
    *,
    page_width: int,
    page_height: int,
    prefer_coords_px: bool,
    old_page_width: int | None = None,
    old_page_height: int | None = None,
) -> bool:
    """Synchronize coords_px and coords_norm for the target page size."""
    old_coords_px = tuple(block.coords_px)
    old_coords_norm = tuple(block.coords_norm)
    old_polygon = list(block.polygon_points) if block.polygon_points else None
    old_polygon_norm = (
        list(block.polygon_points_norm) if block.polygon_points_norm else None
    )

    ow = int(old_page_width) if old_page_width else int(page_width)
    oh = int(old_page_height) if old_page_height else int(page_height)

    if prefer_coords_px:
        _sync_block_from_px(
            block,
            page_width=page_width,
            page_height=page_height,
            old_page_width=ow,
            old_page_height=oh,
        )
    else:
        normalized_coords = normalize_coords_norm(block.coords_norm)
        if normalized_coords is None:
            _sync_block_from_px(
                block,
                page_width=page_width,
                page_height=page_height,
                old_page_width=ow,
                old_page_height=oh,
            )
        else:
            _sync_block_from_norm(
                block,
                page_width=page_width,
                page_height=page_height,
                normalized_coords=normalized_coords,
                old_page_width=ow,
                old_page_height=oh,
            )

    return (
        tuple(block.coords_px) != old_coords_px
        or tuple(block.coords_norm) != old_coords_norm
        or (list(block.polygon_points) if block.polygon_points else None) != old_polygon
        or (list(block.polygon_points_norm) if block.polygon_points_norm else None)
        != old_polygon_norm
    )


def source_pdf_looks_related(document: Document, target_pdf_path: str) -> bool:
    """Best-effort check whether annotation likely belongs to the same PDF."""
    source_name = Path(document.pdf_path).name.casefold()
    target_name = Path(target_pdf_path).name.casefold()
    return bool(source_name and target_name and source_name == target_name)


def _sync_block_from_px(
    block: Block,
    *,
    page_width: int,
    page_height: int,
    old_page_width: int,
    old_page_height: int,
) -> None:
    if block.shape_type == ShapeType.POLYGON and block.polygon_points:
        _resolve_polygon_for_page(
            block,
            page_width=page_width,
            page_height=page_height,
            old_page_width=old_page_width,
            old_page_height=old_page_height,
        )
        return

    coords_px = _sanitize_bbox(
        block.coords_px,
        page_width=page_width,
        page_height=page_height,
    )
    block.coords_px = coords_px
    block.coords_norm = Block.px_to_norm(coords_px, page_width, page_height)


def _sync_block_from_norm(
    block: Block,
    *,
    page_width: int,
    page_height: int,
    normalized_coords: tuple[float, float, float, float],
    old_page_width: int,
    old_page_height: int,
) -> None:
    if block.shape_type == ShapeType.POLYGON and (
        block.polygon_points or block.polygon_points_norm
    ):
        _resolve_polygon_for_page(
            block,
            page_width=page_width,
            page_height=page_height,
            old_page_width=old_page_width,
            old_page_height=old_page_height,
        )
        return

    new_coords_px = Block.norm_to_px(normalized_coords, page_width, page_height)
    new_coords_px = _sanitize_bbox(
        new_coords_px,
        page_width=page_width,
        page_height=page_height,
    )
    block.coords_px = new_coords_px
    block.coords_norm = Block.px_to_norm(new_coords_px, page_width, page_height)


def _resolve_polygon_for_page(
    block: Block,
    *,
    page_width: int,
    page_height: int,
    old_page_width: int,
    old_page_height: int,
) -> None:
    """Восстановить polygon_points для новой страницы и пересчитать bbox из вершин."""
    if block.polygon_points_norm:
        polygon_norm = list(block.polygon_points_norm)
    elif block.polygon_points:
        polygon_norm = Block.polygon_px_to_norm(
            block.polygon_points, old_page_width, old_page_height
        )
    else:
        return

    new_points = Block.polygon_norm_to_px(polygon_norm, page_width, page_height)
    new_points = _clamp_polygon_points(
        new_points, page_width=page_width, page_height=page_height
    )

    if not new_points:
        block.polygon_points = None
        block.polygon_points_norm = None
        coords_px = _sanitize_bbox(
            block.coords_px, page_width=page_width, page_height=page_height
        )
        block.coords_px = coords_px
        block.coords_norm = Block.px_to_norm(coords_px, page_width, page_height)
        return

    block.polygon_points = new_points
    block.polygon_points_norm = polygon_norm
    coords_px = _bbox_from_polygon_points(
        new_points, page_width=page_width, page_height=page_height
    )
    block.coords_px = coords_px
    block.coords_norm = Block.px_to_norm(coords_px, page_width, page_height)


def _sanitize_bbox(
    coords_px: tuple[int, int, int, int] | list[int],
    *,
    page_width: int,
    page_height: int,
) -> tuple[int, int, int, int]:
    max_x = max(page_width - 1, 0)
    max_y = max(page_height - 1, 0)

    x1, y1, x2, y2 = (int(v) for v in coords_px)
    x1 = min(max(x1, 0), max_x)
    y1 = min(max(y1, 0), max_y)
    x2 = min(max(x2, 0), page_width)
    y2 = min(max(y2, 0), page_height)

    if x2 <= x1:
        if page_width <= 1:
            x1, x2 = 0, page_width
        else:
            x1 = min(x1, page_width - 1)
            x2 = min(page_width, x1 + 1)

    if y2 <= y1:
        if page_height <= 1:
            y1, y2 = 0, page_height
        else:
            y1 = min(y1, page_height - 1)
            y2 = min(page_height, y1 + 1)

    return x1, y1, x2, y2


def _clamp_polygon_points(
    polygon_points: Iterable[tuple[int, int]],
    *,
    page_width: int,
    page_height: int,
) -> list[tuple[int, int]]:
    max_x = max(page_width - 1, 0)
    max_y = max(page_height - 1, 0)
    points: list[tuple[int, int]] = []
    for px, py in polygon_points:
        points.append(
            (
                min(max(int(px), 0), max_x),
                min(max(int(py), 0), max_y),
            )
        )
    return points


def _bbox_from_polygon_points(
    polygon_points: list[tuple[int, int]],
    *,
    page_width: int,
    page_height: int,
) -> tuple[int, int, int, int]:
    xs = [point[0] for point in polygon_points]
    ys = [point[1] for point in polygon_points]
    return _sanitize_bbox(
        (min(xs), min(ys), max(xs), max(ys)),
        page_width=page_width,
        page_height=page_height,
    )


