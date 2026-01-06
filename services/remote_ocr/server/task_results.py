"""Генерация результатов OCR"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .ocr_result_merger import merge_ocr_results
from .storage import Job, get_node_full_path, get_node_pdf_r2_key

logger = logging.getLogger(__name__)


def generate_results(
    job: Job, pdf_path: Path, blocks: list, work_dir: Path, datalab_backend=None
) -> str:
    """Генерация результатов OCR (annotation.json + HTML)"""
    from rd_core.models import Block, Document, Page, ShapeType
    from rd_core.ocr import generate_html_from_pages, generate_md_from_pages

    from .pdf_streaming_core import get_page_dimensions_streaming

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

    # Вычисляем r2_prefix
    if job.node_id:
        pdf_r2_key = get_node_pdf_r2_key(job.node_id)
        if pdf_r2_key:
            from pathlib import PurePosixPath

            r2_prefix = str(PurePosixPath(pdf_r2_key).parent)
        else:
            r2_prefix = f"tree_docs/{job.node_id}"
    else:
        r2_prefix = job.r2_prefix

    # Извлекаем путь для ссылок
    if r2_prefix.startswith("tree_docs/"):
        project_name = r2_prefix[len("tree_docs/") :]
    else:
        project_name = job.node_id if job.node_id else job.id

    # Получаем полный путь из дерева проектов (используется в HTML и JSON)
    if job.node_id:
        full_path = get_node_full_path(job.node_id)
        doc_name = full_path if full_path else pdf_path.name
    else:
        doc_name = pdf_path.name

    # annotation.json (для хранения разметки блоков)
    annotation_path = work_dir / "annotation.json"
    doc = Document(pdf_path=doc_name, pages=pages)
    with open(annotation_path, "w", encoding="utf-8") as f:
        json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)

    # Генерация итогового HTML файла
    html_path = work_dir / "ocr_result.html"
    try:
        generate_html_from_pages(
            pages, str(html_path), doc_name=doc_name, project_name=project_name
        )
        logger.info(f"HTML файл сгенерирован: {html_path}")
    except Exception as e:
        logger.warning(f"Ошибка генерации HTML: {e}")

    # Генерация компактного Markdown файла (оптимизирован для LLM)
    md_path = work_dir / "document.md"
    try:
        generate_md_from_pages(
            pages, str(md_path), doc_name=doc_name, project_name=project_name
        )
        if md_path.exists():
            logger.info(f"✅ MD файл сгенерирован: {md_path} ({md_path.stat().st_size} bytes)")
        else:
            logger.error(f"❌ MD файл не создан: {md_path}")
    except Exception as e:
        logger.error(f"❌ Ошибка генерации MD: {e}", exc_info=True)

    # Генерация result.json (annotation + ocr_html + crop_url для каждого блока)
    result_path = work_dir / "result.json"
    try:
        merge_ocr_results(
            annotation_path,
            html_path,
            result_path,
            project_name=project_name,
            doc_name=doc_name,
        )
    except Exception as e:
        logger.warning(f"Ошибка генерации result.json: {e}")

    # Верификация и повторное распознавание пропущенных блоков
    if datalab_backend and result_path.exists():
        from .block_verification import verify_and_retry_missing_blocks
        
        try:
            logger.info("Запуск верификации блоков...")
            verify_and_retry_missing_blocks(result_path, pdf_path, work_dir, datalab_backend)
        except Exception as e:
            logger.warning(f"Ошибка верификации блоков: {e}", exc_info=True)

    return r2_prefix
