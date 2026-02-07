"""Генератор HTML (ocr.html) из OCR результатов."""
import json as json_module
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from .generator_common import (
    HTML_FOOTER,
    INHERITABLE_STAMP_FIELDS,
    collect_block_groups,
    collect_inheritable_stamp_data,
    extract_image_ocr_data,
    find_page_stamp,
    format_stamp_parts,
    get_block_armor_id,
    get_html_header,
    is_image_ocr_json,
    sanitize_html,
)

logger = logging.getLogger(__name__)


def _format_image_ocr_html(data: dict) -> str:
    """Форматировать данные OCR изображения в компактный HTML."""
    img_data = extract_image_ocr_data(data)
    parts = []

    # Заголовок: [ИЗОБРАЖЕНИЕ] Тип: XXX | Оси: XXX
    header_parts = ["<b>[ИЗОБРАЖЕНИЕ]</b>"]
    if img_data.get("zone_name") and img_data["zone_name"] != "Не определено":
        header_parts.append(f"Тип: {img_data['zone_name']}")
    if img_data.get("grid_lines") and img_data["grid_lines"] != "Не определены":
        header_parts.append(f"Оси: {img_data['grid_lines']}")
    if img_data.get("location_text"):
        header_parts.append(img_data["location_text"])
    parts.append(f"<p>{' | '.join(header_parts)}</p>")

    # Краткое описание
    if img_data.get("content_summary"):
        parts.append(f"<p><b>Краткое описание:</b> {img_data['content_summary']}</p>")

    # Детальное описание
    if img_data.get("detailed_description"):
        parts.append(f"<p><b>Описание:</b> {img_data['detailed_description']}</p>")

    # Распознанный текст
    if img_data.get("clean_ocr_text"):
        parts.append(f"<p><b>Текст на чертеже:</b> {img_data['clean_ocr_text']}</p>")

    # Ключевые сущности - через запятую
    if img_data.get("key_entities"):
        entities_str = ", ".join(img_data["key_entities"])
        parts.append(f"<p><b>Сущности:</b> {entities_str}</p>")

    return "\n".join(parts) if parts else ""


def _extract_html_from_ocr_text(ocr_text: str) -> str:
    """
    Извлечь HTML из ocr_text.

    ocr_text может содержать:
    - Чистый HTML от Datalab
    - JSON с полем html или children[].html
    - JSON блока изображения (location, content_summary, etc.)
    - Просто текст (fallback)
    """
    if not ocr_text:
        return ""

    text = ocr_text.strip()
    if not text:
        return ""

    # Если начинается с HTML тега или закрывающего тега - обрабатываем как HTML
    if text.startswith("<") or text.startswith("</"):
        return sanitize_html(text)

    # Пробуем распарсить как JSON
    try:
        parsed = json_module.loads(text)

        if isinstance(parsed, dict):
            # Проверяем, это JSON блока изображения?
            if is_image_ocr_json(parsed):
                formatted = _format_image_ocr_html(parsed)
                if formatted:
                    return formatted

            # Иначе пробуем извлечь HTML из структуры
            html = _extract_html_from_parsed(parsed)
            if html:
                return sanitize_html(html)
    except json_module.JSONDecodeError:
        pass

    # Fallback: возвращаем как есть (экранируем HTML)
    return f"<pre>{_escape_html(text)}</pre>"


def _extract_html_from_parsed(data: Any) -> str:
    """Извлечь HTML из распарсенного JSON."""
    html_parts = []

    if isinstance(data, dict):
        if "html" in data and isinstance(data["html"], str):
            html_parts.append(data["html"])
        elif "children" in data and isinstance(data["children"], list):
            for child in data["children"]:
                html_parts.append(_extract_html_from_parsed(child))
    elif isinstance(data, list):
        for item in data:
            html_parts.append(_extract_html_from_parsed(item))

    return "".join(html_parts)


def _escape_html(text: str) -> str:
    """Экранировать HTML спецсимволы."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_stamp_html(stamp_data: Dict) -> str:
    """Форматировать данные штампа в компактный HTML блок."""
    parts = format_stamp_parts(stamp_data)
    if not parts:
        return ""

    html_parts = [f"<b>{key}:</b> {value}" for key, value in parts]
    return '<div class="stamp-info">' + " | ".join(html_parts) + "</div>"


def _format_inherited_stamp_html(inherited_data: Dict) -> str:
    """Форматировать унаследованные данные штампа в компактный HTML блок."""
    parts = []

    if inherited_data.get("document_code"):
        parts.append(f"<b>Шифр:</b> {inherited_data['document_code']}")
    if inherited_data.get("stage"):
        parts.append(f"<b>Стадия:</b> {inherited_data['stage']}")
    if inherited_data.get("project_name"):
        parts.append(f"<b>Объект:</b> {inherited_data['project_name']}")
    if inherited_data.get("organization"):
        parts.append(f"<b>Организация:</b> {inherited_data['organization']}")

    if not parts:
        return ""

    return '<div class="stamp-info stamp-inherited">' + " | ".join(parts) + "</div>"


def generate_html_from_pages(
    pages: List, output_path: str, doc_name: str = None, project_name: str = None
) -> str:
    """
    Генерация итогового HTML файла (ocr.html) из OCR результатов.

    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения HTML файла
        doc_name: имя документа для заголовка
        project_name: имя проекта для ссылок на R2

    Returns:
        Путь к сохранённому файлу
    """
    try:
        from rd_core.models import BlockType

        r2_public_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        title = doc_name or "OCR Result"

        # Используем общий HTML шаблон
        html_parts = [get_html_header(title)]

        # Собираем блоки по группам
        groups = collect_block_groups(pages)

        # Собираем общие данные штампа для страниц без штампа
        inherited_stamp_data = collect_inheritable_stamp_data(pages)
        inherited_stamp_html = (
            _format_inherited_stamp_html(inherited_stamp_data)
            if inherited_stamp_data
            else ""
        )

        block_count = 0
        for page in pages:
            # Находим данные штампа для этой страницы
            page_stamp = find_page_stamp(page.blocks)
            if page_stamp:
                # Мержим с inherited: заполняем пустые поля из унаследованных
                merged_stamp = dict(page_stamp)
                if inherited_stamp_data:
                    for field in INHERITABLE_STAMP_FIELDS:
                        if not merged_stamp.get(field):
                            if inherited_stamp_data.get(field):
                                merged_stamp[field] = inherited_stamp_data[field]
                stamp_html = _format_stamp_html(merged_stamp)
            elif inherited_stamp_data:
                stamp_html = inherited_stamp_html
            else:
                stamp_html = ""

            for idx, block in enumerate(page.blocks):
                # Пропускаем блоки штампа
                if getattr(block, "category_code", None) == "stamp":
                    continue

                block_count += 1
                block_type = block.block_type.value
                page_num = page.page_number + 1 if page.page_number is not None else ""

                html_parts.append(f'<div class="block block-type-{block_type}">')
                html_parts.append(
                    f'<div class="block-header">Блок #{idx + 1} (стр. {page_num}) | Тип: {block_type}</div>'
                )
                html_parts.append('<div class="block-content">')

                # Маркер BLOCK: XXXX-XXXX-XXX
                armor_code = get_block_armor_id(block.id)
                html_parts.append(f"<p>BLOCK: {armor_code}</p>")

                # Grouped blocks
                group_id = getattr(block, "group_id", None)
                if group_id and group_id in groups:
                    group_name = getattr(block, "group_name", None) or group_id
                    group_block_ids = [get_block_armor_id(b.id) for b in groups[group_id]]
                    html_parts.append(
                        f'<p><b>Grouped blocks:</b> {group_name} [{", ".join(group_block_ids)}]</p>'
                    )

                # Linked block
                linked_id = getattr(block, "linked_block_id", None)
                if linked_id:
                    linked_armor = get_block_armor_id(linked_id)
                    html_parts.append(f"<p><b>Linked block:</b> {linked_armor}</p>")

                # Created at
                created_at = getattr(block, "created_at", None)
                if created_at:
                    html_parts.append(f"<p><b>Created:</b> {created_at}</p>")

                # Информация о штампе
                if stamp_html:
                    html_parts.append(stamp_html)

                # Для IMAGE блоков добавляем ссылку на изображение
                if block.block_type == BlockType.IMAGE and block.image_file:
                    crop_filename = Path(block.image_file).name
                    if project_name:
                        image_uri = f"{r2_public_url}/tree_docs/{project_name}/crops/{crop_filename}"
                        html_parts.append(
                            f'<p><a href="{image_uri}" target="_blank"><b>🖼️ Открыть кроп изображения</b></a></p>'
                        )

                # Извлекаем HTML из ocr_text
                block_html = _extract_html_from_ocr_text(block.ocr_text)
                html_parts.append(block_html)

                html_parts.append("</div></div>")

        html_parts.append(HTML_FOOTER)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))

        logger.info(f"HTML файл сохранён: {output_file} ({block_count} блоков)")
        return str(output_file)

    except Exception as e:
        logger.error(f"Ошибка генерации HTML: {e}", exc_info=True)
        raise
