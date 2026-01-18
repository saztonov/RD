"""Генерация результатов OCR"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .r2_paths import get_doc_prefix
from .storage import Job, get_node_full_path

logger = logging.getLogger(__name__)


def generate_results(
    job: Job, pdf_path: Path, blocks: list, work_dir: Path, datalab_backend=None
) -> str:
    """Генерация результатов OCR.

    Генерируемые файлы:
      - annotation.json (локально, для метаданных блоков - не загружается в R2)
      - document.md (загружается в R2 как {doc_stem}_result.md)
    """
    from rd_domain.models import Block, Document, Page, ShapeType
    from rd_pipeline.output import generate_md_from_pages
    from rd_pipeline.processing.streaming_pdf import get_page_dimensions_streaming

    # Логирование состояния блоков
    blocks_with_ocr = sum(1 for b in blocks if b.ocr_text)
    logger.info(
        f"generate_results: всего блоков={len(blocks)}, с ocr_text={blocks_with_ocr}"
    )

    # Сохраняем оригинальный порядок блоков (индекс в исходном списке)
    blocks_by_page: dict[int, list[tuple[int, any]]] = {}
    for orig_idx, b in enumerate(blocks):
        blocks_by_page.setdefault(b.page_index, []).append((orig_idx, b))

    # Streaming получение размеров страниц
    page_dims = get_page_dimensions_streaming(str(pdf_path))

    pages = []
    for page_idx in sorted(blocks_by_page.keys()):
        dims = page_dims.get(page_idx)
        width, height = dims if dims else (0, 0)
        page_blocks = [
            b for _, b in sorted(blocks_by_page[page_idx], key=lambda x: x[0])
        ]

        # Пересчитываем coords_px и polygon_points
        if width > 0 and height > 0:
            for block in page_blocks:
                old_x1, old_y1, old_x2, old_y2 = block.coords_px
                old_bbox_w = old_x2 - old_x1 if old_x2 != old_x1 else 1
                old_bbox_h = old_y2 - old_y1 if old_y2 != old_y1 else 1

                block.coords_px = Block.norm_to_px(block.coords_norm, width, height)

                if block.shape_type == ShapeType.POLYGON and block.polygon_points:
                    new_x1, new_y1, new_x2, new_y2 = block.coords_px
                    new_bbox_w = new_x2 - new_x1 if new_x2 != new_x1 else 1
                    new_bbox_h = new_y2 - new_y1 if new_y2 != new_y1 else 1
                    block.polygon_points = [
                        (
                            int(new_x1 + (px - old_x1) / old_bbox_w * new_bbox_w),
                            int(new_y1 + (py - old_y1) / old_bbox_h * new_bbox_h),
                        )
                        for px, py in block.polygon_points
                    ]

        pages.append(
            Page(page_number=page_idx, width=width, height=height, blocks=page_blocks)
        )

    # Структура путей: tree_docs/{node_id}/
    if not job.node_id:
        raise ValueError("node_id is required for OCR job")
    r2_prefix = get_doc_prefix(job.node_id)

    # Получаем полный путь из дерева проектов для имени документа
    full_path = get_node_full_path(job.node_id)
    doc_name = full_path if full_path else pdf_path.name
    project_name = job.node_id  # упрощено, без /ocr_runs/{job_id}

    # annotation.json (локально, для метаданных - не загружается в R2)
    annotation_path = work_dir / "annotation.json"
    doc = Document(pdf_path=doc_name, pages=pages)
    with open(annotation_path, "w", encoding="utf-8") as f:
        json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)

    # Генерация компактного Markdown файла
    md_path = work_dir / "document.md"
    try:
        generate_md_from_pages(
            pages, str(md_path), doc_name=doc_name, project_name=project_name
        )
        if md_path.exists():
            logger.info(f"MD файл сгенерирован: {md_path} ({md_path.stat().st_size} bytes)")
        else:
            logger.error(f"MD файл не создан: {md_path}")
    except Exception as e:
        logger.error(f"Ошибка генерации MD: {e}", exc_info=True)

    return r2_prefix
