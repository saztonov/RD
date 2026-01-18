"""Генерация результатов OCR"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from rd_pipeline.processing.merge import merge_ocr_results
from .qa_manifest import generate_qa_manifest
from .storage import Job, get_node_full_path

logger = logging.getLogger(__name__)


def save_text_blocks(blocks: list, work_dir: Path) -> int:
    """Сохранить каждый TEXT блок с ocr_text в отдельный JSON файл.

    Args:
        blocks: список Block объектов
        work_dir: рабочая директория

    Returns:
        количество сохранённых блоков
    """
    from rd_domain.models import BlockType

    text_blocks_dir = work_dir / "text_blocks"
    text_blocks_dir.mkdir(exist_ok=True)

    saved_count = 0
    for block in blocks:
        # Проверяем тип блока и наличие OCR текста
        if block.block_type != BlockType.TEXT:
            continue
        if not block.ocr_text:
            continue

        data = {
            "block_id": block.id,
            "page_index": block.page_index,
            "coords_norm": list(block.coords_norm) if block.coords_norm else [],
            "coords_px": list(block.coords_px) if block.coords_px else [],
            "block_type": block.block_type.value,
            "ocr_text": block.ocr_text,
            "created_at": datetime.utcnow().isoformat(),
        }

        # Добавляем опциональные поля
        if hasattr(block, "category_code") and block.category_code:
            data["category_code"] = block.category_code

        path = text_blocks_dir / f"{block.id}.json"
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            saved_count += 1
        except Exception as e:
            logger.warning(f"Ошибка сохранения text_block {block.id}: {e}")

    logger.info(f"Сохранено {saved_count} текстовых блоков в {text_blocks_dir}")
    return saved_count


def generate_results(
    job: Job, pdf_path: Path, blocks: list, work_dir: Path, datalab_backend=None
) -> str:
    """Генерация результатов OCR (annotation.json + HTML)"""
    from rd_domain.models import Block, Document, Page, ShapeType
    from rd_pipeline.output import generate_html_from_pages, generate_md_from_pages
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

    # Вычисляем r2_prefix (изолированный для каждой задачи)
    if job.node_id:
        r2_prefix = f"tree_docs/{job.node_id}/ocr_runs/{job.id}"
    else:
        r2_prefix = job.r2_prefix

    # Получаем полный путь из дерева проектов (используется в HTML и JSON)
    if job.node_id:
        full_path = get_node_full_path(job.node_id)
        doc_name = full_path if full_path else pdf_path.name
        # project_name для HTML генераторов (для ссылок на кропы в HTML)
        project_name = f"{job.node_id}/ocr_runs/{job.id}"
    else:
        doc_name = pdf_path.name
        project_name = job.id

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

    # Генерация компактного Markdown файла (оптимизирован для LLM, с дедупликацией linked блоков)
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
            r2_prefix=r2_prefix,
            job_id=str(job.id),
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

    # Сохранение отдельных текстовых блоков для просмотра
    try:
        save_text_blocks(blocks, work_dir)
    except Exception as e:
        logger.warning(f"Ошибка сохранения text_blocks: {e}", exc_info=True)

    # Генерация QA манифеста (для Q&A приложения)
    try:
        qa_manifest_path = generate_qa_manifest(
            work_dir=work_dir,
            r2_prefix=r2_prefix,
            job_id=str(job.id),
            node_id=job.node_id,
        )
        if qa_manifest_path:
            logger.info(f"QA manifest сгенерирован: {qa_manifest_path}")
    except Exception as e:
        logger.warning(f"Ошибка генерации QA manifest: {e}", exc_info=True)

    return r2_prefix
