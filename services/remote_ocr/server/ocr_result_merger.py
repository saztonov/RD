"""Объединение OCR результатов: annotation.json + ocr_result.html -> result.json"""
from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Optional

from rd_core.ocr.generator_common import (
    HTML_FOOTER,
    INHERITABLE_STAMP_FIELDS,
    collect_inheritable_stamp_data_dict,
    get_html_header,
    parse_stamp_json,
    propagate_stamp_data,
)

from .ocr_html_parser import build_segments_from_html

logger = logging.getLogger(__name__)


def _build_crop_url(block_id: str, r2_public_url: str, project_name: str) -> str:
    """Сформировать URL кропа для блока."""
    return f"{r2_public_url}/tree_docs/{project_name}/crops/{block_id}.pdf"


def merge_ocr_results(
    annotation_path: Path,
    ocr_html_path: Path,
    output_path: Path,
    project_name: Optional[str] = None,
    r2_public_url: Optional[str] = None,
    score_cutoff: int = 90,
    doc_name: Optional[str] = None,
) -> bool:
    """
    Объединить annotation.json и ocr_result.html в result.json.

    Добавляет к каждому блоку:
    - ocr_html: HTML-фрагмент блока
    - ocr_json: распарсенный JSON из ocr_text (для IMAGE блоков)
    - crop_url: ссылка на кроп (для IMAGE блоков)
    - ocr_meta: {method, match_score, marker_text_sample}

    Returns:
        True если успешно, False при ошибке
    """
    if not r2_public_url:
        r2_public_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")

    try:
        if not annotation_path.exists():
            logger.warning(f"annotation.json не найден: {annotation_path}")
            return False

        if not ocr_html_path.exists():
            logger.warning(f"ocr_result.html не найден: {ocr_html_path}")
            return False

        with open(annotation_path, "r", encoding="utf-8") as f:
            ann = json.load(f)

        expected_ids = [
            b["id"] for p in ann.get("pages", []) for b in p.get("blocks", [])
        ]

        if not expected_ids:
            logger.info("Нет блоков для обработки")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(ann, f, ensure_ascii=False, indent=2)
            return True

        with open(ocr_html_path, "r", encoding="utf-8") as f:
            html_text = f.read()

        segments, meta = build_segments_from_html(
            html_text, expected_ids, score_cutoff=score_cutoff
        )

        result = deepcopy(ann)
        missing = []
        matched = 0

        for page in result.get("pages", []):
            # Конвертируем page_number в 1-based для внешнего формата
            if "page_number" in page:
                page["page_number"] = page["page_number"] + 1
            for blk in page.get("blocks", []):
                bid = blk["id"]
                block_type = blk.get("block_type", "text")

                # Конвертируем page_index в 1-based для внешнего формата
                if "page_index" in blk:
                    blk["page_index"] = blk["page_index"] + 1

                # HTML фрагмент
                blk["ocr_html"] = segments.get(bid, "")
                blk["ocr_meta"] = meta.get(
                    bid, {"method": [], "match_score": 0.0, "marker_text_sample": ""}
                )

                # Для IMAGE блоков: парсим JSON из ocr_text и добавляем crop_url
                if block_type == "image":
                    ocr_text = blk.get("ocr_text", "")
                    parsed_json = parse_stamp_json(ocr_text)  # Используем общую функцию
                    if parsed_json:
                        blk["ocr_json"] = parsed_json

                    # Добавляем ссылку на кроп (кроме штампов)
                    if blk.get("category_code") != "stamp":
                        if project_name:
                            blk["crop_url"] = _build_crop_url(
                                bid, r2_public_url, project_name
                            )
                        elif blk.get("image_file"):
                            crop_name = Path(blk["image_file"]).name
                            blk["crop_url"] = f"{r2_public_url}/crops/{crop_name}"

                if blk["ocr_html"]:
                    matched += 1
                else:
                    missing.append(bid)

        # Собираем общие данные штампа (используем общую функцию)
        inherited_stamp = collect_inheritable_stamp_data_dict(result.get("pages", []))

        # Распространение данных штампа (используем общую функцию)
        for page in result.get("pages", []):
            propagate_stamp_data(page, inherited_stamp)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        if missing:
            logger.warning(
                f"Не найдено HTML для {len(missing)} блоков. Примеры: {missing[:3]}"
            )

        logger.info(
            f"result.json сохранён: {output_path} ({matched}/{len(expected_ids)} блоков сопоставлено)"
        )

        # Регенерируем HTML из разделённых ocr_html
        regenerate_html_from_result(result, ocr_html_path, doc_name=doc_name)

        # Регенерируем MD из разделённых ocr_html
        md_path = output_path.parent / "document.md"
        regenerate_md_from_result(result, md_path, doc_name=doc_name)

        return True

    except Exception as e:
        logger.error(f"Ошибка объединения OCR результатов: {e}", exc_info=True)
        return False


def regenerate_md_from_result(
    result: dict, output_path: Path, doc_name: Optional[str] = None
) -> None:
    """Регенерировать Markdown файл из result.json."""
    from rd_core.ocr.md_generator import generate_md_from_result

    try:
        generate_md_from_result(result, output_path, doc_name=doc_name)
    except Exception as e:
        logger.warning(f"Ошибка регенерации MD: {e}")


def regenerate_html_from_result(
    result: dict, output_path: Path, doc_name: Optional[str] = None
) -> None:
    """
    Регенерировать HTML файл из result.json с правильно разделёнными блоками.
    Использует ocr_html (уже разделённый по маркерам) вместо ocr_text.
    """
    if not doc_name:
        doc_name = result.get("pdf_path", "OCR Result")

    # Используем общий HTML шаблон
    html_parts = [get_html_header(doc_name)]

    block_count = 0
    for page in result.get("pages", []):
        page_num = page.get("page_number", "")

        for idx, blk in enumerate(page.get("blocks", [])):
            # Пропускаем блоки штампа
            if blk.get("category_code") == "stamp":
                continue

            block_id = blk.get("id", "")
            block_type = blk.get("block_type", "text")
            ocr_html = blk.get("ocr_html", "")

            if not ocr_html:
                continue

            block_count += 1

            html_parts.append(f'<div class="block block-type-{block_type}">')
            html_parts.append(
                f'<div class="block-header">Блок #{idx + 1} (стр. {page_num}) | Тип: {block_type}</div>'
            )
            html_parts.append('<div class="block-content">')
            html_parts.append(f"<p>BLOCK: {block_id}</p>")

            # Для IMAGE блоков добавляем ссылку на кроп
            if block_type == "image" and blk.get("crop_url"):
                if "Открыть кроп изображения" not in ocr_html:
                    crop_url = blk["crop_url"]
                    html_parts.append(
                        f'<p><a href="{crop_url}" target="_blank"><b>🖼️ Открыть кроп изображения</b></a></p>'
                    )

            html_parts.append(ocr_html)
            html_parts.append("</div></div>")

    html_parts.append(HTML_FOOTER)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))

    logger.info(
        f"HTML регенерирован из result.json: {output_path} ({block_count} блоков)"
    )
