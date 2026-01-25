"""Генератор Markdown (_document.md) из OCR результатов."""
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..generator_common import (
    collect_block_groups,
    collect_inheritable_stamp_data,
    find_page_stamp,
    get_block_armor_id,
)
from .formatter import format_stamp_md, process_ocr_content
from .html_converter import html_to_markdown
from .link_collector import (
    collect_image_text_links_from_pages,
    collect_image_text_links_from_result,
    get_text_block_content,
)

logger = logging.getLogger(__name__)


def generate_md_from_pages(
    pages: List,
    output_path: str,
    doc_name: str = None,
    project_name: str = None,
) -> str:
    """
    Генерация компактного Markdown файла (_document.md) из OCR результатов.
    Группировка по страницам, оптимизация для LLM.

    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения MD файла
        doc_name: имя документа для заголовка
        project_name: имя проекта (не используется в MD)

    Returns:
        Путь к сохранённому файлу
    """
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        title = doc_name or "OCR Result"

        # Собираем блоки по группам
        groups = collect_block_groups(pages)

        # Собираем данные штампа
        inherited_stamp_data = collect_inheritable_stamp_data(pages)

        # Собираем связи IMAGE→TEXT для объединения
        image_to_text = collect_image_text_links_from_pages(pages)

        # Индекс всех блоков для быстрого доступа по ID
        all_blocks_index: Dict[str, Any] = {}
        for page in pages:
            for block in page.blocks:
                all_blocks_index[block.id] = block

        # TEXT блоки, которые будут встроены в IMAGE (не выводить отдельно)
        embedded_text_ids = set(image_to_text.values())

        md_parts = []

        # === HEADER ===
        md_parts.append(f"# {title}")
        md_parts.append("")
        md_parts.append(f"Сгенерировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

        # Штамп документа
        if inherited_stamp_data:
            stamp_str = format_stamp_md(inherited_stamp_data)
            if stamp_str:
                md_parts.append(f"**Штамп:** {stamp_str}")

        md_parts.append("")
        md_parts.append("---")
        md_parts.append("")

        # === БЛОКИ - группировка по страницам ===
        block_count = 0
        current_page_num = None

        for page in pages:
            page_num = page.page_number + 1 if page.page_number is not None else 0

            # Проверяем есть ли блоки кроме штампов
            non_stamp_blocks = [b for b in page.blocks if getattr(b, "category_code", None) != "stamp"]
            if not non_stamp_blocks:
                continue

            # Заголовок страницы
            if page_num != current_page_num:
                current_page_num = page_num
                md_parts.append(f"## СТРАНИЦА {page_num}")

                # Добавляем информацию из штампа страницы (лист, наименование)
                page_stamp = find_page_stamp(page.blocks)
                if page_stamp:
                    sheet_num = page_stamp.get("sheet_number", "")
                    total_sheets = page_stamp.get("total_sheets", "")
                    sheet_name = page_stamp.get("sheet_name", "")

                    if sheet_num or total_sheets:
                        if total_sheets:
                            md_parts.append(f"**Лист:** {sheet_num} (из {total_sheets})")
                        else:
                            md_parts.append(f"**Лист:** {sheet_num}")

                    if sheet_name:
                        md_parts.append(f"**Наименование листа:** {sheet_name}")

                md_parts.append("")

            for block in page.blocks:
                # Пропускаем блоки штампа
                if getattr(block, "category_code", None) == "stamp":
                    continue

                # Пропускаем TEXT блоки, которые встроены в IMAGE
                if block.id in embedded_text_ids:
                    continue

                block_count += 1
                armor_code = get_block_armor_id(block.id)
                block_type = block.block_type.value.upper()

                # Заголовок блока (H3)
                header_parts = [f"### BLOCK [{block_type}]: {armor_code}"]

                # Метаданные - компактно в одну строку под заголовком
                meta_parts = []

                # Linked block - НЕ выводим для IMAGE с встроенным TEXT
                linked_id = getattr(block, "linked_block_id", None)
                has_embedded_text = block.id in image_to_text
                if linked_id and not has_embedded_text:
                    meta_parts.append(f"→{get_block_armor_id(linked_id)}")

                # Grouped blocks
                group_id = getattr(block, "group_id", None)
                if group_id and group_id in groups:
                    group_name = getattr(block, "group_name", None) or "группа"
                    group_block_ids = [get_block_armor_id(b.id) for b in groups[group_id]]
                    meta_parts.append(f"📦{group_name}[{','.join(group_block_ids)}]")

                md_parts.append(" ".join(header_parts))
                if meta_parts:
                    md_parts.append(" ".join(meta_parts))

                # Содержимое блока
                content = process_ocr_content(block.ocr_text)
                if content:
                    md_parts.append(content)

                # Для IMAGE блоков - добавляем встроенный текст из связанного TEXT блока
                if has_embedded_text:
                    text_block_id = image_to_text[block.id]
                    embedded_content = get_text_block_content(
                        text_block_id, all_blocks_index, is_dict=False
                    )
                    if embedded_content:
                        md_parts.append("")
                        md_parts.append("**Распознанный OCR текст на чертеже:**")
                        md_parts.append(embedded_content)

                md_parts.append("")

        # Записываем файл
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md_parts))

        logger.info(f"MD файл сохранён: {output_file} ({block_count} блоков)")
        return str(output_file)

    except Exception as e:
        logger.error(f"Ошибка генерации MD: {e}", exc_info=True)
        raise


def generate_md_from_result(
    result: dict, output_path: Path, doc_name: Optional[str] = None
) -> None:
    """
    Генерировать Markdown файл из result.json с правильно разделёнными блоками.
    Группировка по страницам.

    Args:
        result: словарь с результатами OCR (pages, blocks)
        output_path: путь для сохранения MD файла
        doc_name: имя документа для заголовка
    """
    if not doc_name:
        doc_name = result.get("pdf_path", "OCR Result")

    md_parts = []

    # === HEADER ===
    md_parts.append(f"# {doc_name}")
    md_parts.append("")
    md_parts.append(f"Сгенерировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # Собираем данные штампа из первого блока
    first_stamp = None
    for page in result.get("pages", []):
        for blk in page.get("blocks", []):
            if blk.get("stamp_data"):
                first_stamp = blk["stamp_data"]
                break
        if first_stamp:
            break

    if first_stamp:
        stamp_str = format_stamp_md(first_stamp)
        if stamp_str:
            md_parts.append(f"**Штамп:** {stamp_str}")

    md_parts.append("")
    md_parts.append("---")
    md_parts.append("")

    # Собираем группы блоков
    groups: Dict[str, List[str]] = {}
    for page in result.get("pages", []):
        for blk in page.get("blocks", []):
            group_id = blk.get("group_id")
            if group_id:
                if group_id not in groups:
                    groups[group_id] = []
                groups[group_id].append(blk.get("id", ""))

    # Собираем связи IMAGE→TEXT для объединения
    pages_list = result.get("pages", [])
    image_to_text = collect_image_text_links_from_result(pages_list)

    # Индекс всех блоков для быстрого доступа по ID
    all_blocks_index: Dict[str, Dict] = {}
    for page in pages_list:
        for blk in page.get("blocks", []):
            block_id = blk.get("id", "")
            if block_id:
                all_blocks_index[block_id] = blk

    # TEXT блоки, которые будут встроены в IMAGE (не выводить отдельно)
    embedded_text_ids = set(image_to_text.values())

    # === БЛОКИ - группировка по страницам ===
    block_count = 0
    current_page_num = None

    for page in result.get("pages", []):
        page_num = page.get("page_number", 0)

        # Проверяем есть ли блоки кроме штампов
        non_stamp_blocks = [b for b in page.get("blocks", []) if b.get("category_code") != "stamp"]
        if not non_stamp_blocks:
            continue

        # Заголовок страницы
        if page_num != current_page_num:
            current_page_num = page_num
            md_parts.append(f"## СТРАНИЦА {page_num}")

            # Ищем штамп на странице для получения информации о листе
            page_stamp = None
            for blk in page.get("blocks", []):
                if blk.get("category_code") == "stamp":
                    page_stamp = blk.get("stamp_data") or blk.get("ocr_json")
                    break

            if page_stamp:
                sheet_num = page_stamp.get("sheet_number", "")
                total_sheets = page_stamp.get("total_sheets", "")
                sheet_name = page_stamp.get("sheet_name", "")

                if sheet_num or total_sheets:
                    if total_sheets:
                        md_parts.append(f"**Лист:** {sheet_num} (из {total_sheets})")
                    else:
                        md_parts.append(f"**Лист:** {sheet_num}")

                if sheet_name:
                    md_parts.append(f"**Наименование листа:** {sheet_name}")

            md_parts.append("")

        for blk in page.get("blocks", []):
            # Пропускаем блоки штампа
            if blk.get("category_code") == "stamp":
                continue

            block_id = blk.get("id", "")

            # Пропускаем TEXT блоки, которые встроены в IMAGE
            if block_id in embedded_text_ids:
                continue

            block_type = blk.get("block_type", "text").upper()
            ocr_html = blk.get("ocr_html", "")
            ocr_text = blk.get("ocr_text", "")

            block_count += 1

            # Заголовок блока (H3)
            header_parts = [f"### BLOCK [{block_type}]: {block_id}"]

            # Метаданные - компактно в одну строку под заголовком
            meta_parts = []

            # Linked block - НЕ выводим для IMAGE с встроенным TEXT
            has_embedded_text = block_id in image_to_text
            if blk.get("linked_block_id") and not has_embedded_text:
                meta_parts.append(f"→{blk['linked_block_id']}")

            # Grouped blocks
            group_id = blk.get("group_id")
            if group_id and group_id in groups:
                group_name = blk.get("group_name") or "группа"
                group_block_ids = groups[group_id]
                meta_parts.append(f"📦{group_name}[{','.join(group_block_ids)}]")

            md_parts.append(" ".join(header_parts))
            if meta_parts:
                md_parts.append(" ".join(meta_parts))

            # Содержимое блока
            content = ""
            if ocr_html:
                content = html_to_markdown(ocr_html)
            elif ocr_text:
                content = process_ocr_content(ocr_text)

            if content:
                md_parts.append(content)
            else:
                md_parts.append("*(нет данных)*")

            # Для IMAGE блоков - добавляем встроенный текст из связанного TEXT блока
            if has_embedded_text:
                text_block_id = image_to_text[block_id]
                embedded_content = get_text_block_content(
                    text_block_id, all_blocks_index, is_dict=True
                )
                if embedded_content:
                    md_parts.append("")
                    md_parts.append("**Распознанный OCR текст на чертеже:**")
                    md_parts.append(embedded_content)

            md_parts.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_parts))

    logger.info(f"MD регенерирован из result.json: {output_path} ({block_count} блоков)")
