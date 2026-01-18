"""Генератор Markdown (_document.md) из OCR результатов (оптимизирован для LLM)."""
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from rd_pipeline.common import (
    build_linked_blocks_index,
    build_linked_blocks_index_dict,
    collect_block_groups,
    collect_inheritable_stamp_data,
    find_page_stamp,
    get_block_armor_id,
)
from rd_pipeline.output.md_converters import html_to_markdown
from rd_pipeline.output.md_formatters import (
    format_stamp_md,
    process_ocr_content,
)

logger = logging.getLogger(__name__)

# Алиасы для обратной совместимости (приватные функции)
_format_stamp_md = format_stamp_md
_html_to_markdown = html_to_markdown
_process_ocr_content = process_ocr_content


def generate_md_from_pages(
    pages: List,
    output_path: str,
    doc_name: str = None,
    project_name: str = None,
) -> str:
    """
    Генерация компактного Markdown файла (_document.md) из OCR результатов.
    Группировка по страницам, оптимизация для LLM.
    Linked TEXT блоки (derived) пропускаются, их текст добавляется к IMAGE блокам.

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

        # Построить индекс linked блоков для дедупликации
        linked_index = build_linked_blocks_index(pages)
        if linked_index["derived_ids"]:
            logger.info(
                f"Linked blocks: {len(linked_index['derived_ids'])} derived (пропущены)"
            )

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

                # Пропускаем derived блоки (linked TEXT блоки)
                if block.id in linked_index["derived_ids"]:
                    continue

                block_count += 1
                armor_code = get_block_armor_id(block.id)
                block_type = block.block_type.value.upper()

                # Заголовок блока (H3)
                header_parts = [f"### BLOCK [{block_type}]: {armor_code}"]

                # Метаданные - компактно в одну строку под заголовком
                meta_parts = []

                # Linked block
                linked_id = getattr(block, "linked_block_id", None)
                if linked_id:
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

                # Добавляем linked_block_clean_ocr_text для IMAGE блоков
                linked_text = linked_index["linked_ocr_text"].get(block.id)
                if linked_text:
                    md_parts.append(f"\n**Текст из связанного блока:** {linked_text}")

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
    result: dict,
    output_path: Path,
    doc_name: Optional[str] = None,
) -> None:
    """
    Генерировать Markdown файл из result.json с правильно разделёнными блоками.
    Группировка по страницам.
    Linked TEXT блоки (derived) пропускаются, их текст добавляется к IMAGE блокам.

    Args:
        result: словарь с результатами OCR (pages, blocks)
        output_path: путь для сохранения MD файла
        doc_name: имя документа для заголовка
    """
    if not doc_name:
        doc_name = result.get("pdf_path", "OCR Result")

    # Построить индекс linked блоков для дедупликации
    linked_index = build_linked_blocks_index_dict(result.get("pages", []))
    if linked_index["derived_ids"]:
        logger.info(
            f"Linked blocks (result): {len(linked_index['derived_ids'])} derived (пропущены)"
        )

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

            # Пропускаем derived блоки (linked TEXT блоки)
            if block_id in linked_index["derived_ids"]:
                continue

            block_type = blk.get("block_type", "text").upper()
            ocr_html = blk.get("ocr_html", "")
            ocr_text = blk.get("ocr_text", "")

            block_count += 1

            # Заголовок блока (H3)
            header_parts = [f"### BLOCK [{block_type}]: {block_id}"]

            # Метаданные - компактно в одну строку под заголовком
            meta_parts = []

            # Linked block
            if blk.get("linked_block_id"):
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

            # Добавляем linked_block_clean_ocr_text для IMAGE блоков
            linked_text = linked_index["linked_ocr_text"].get(block_id)
            if linked_text:
                md_parts.append(f"\n**Текст из связанного блока:** {linked_text}")

            md_parts.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_parts))

    logger.info(f"MD регенерирован из result.json: {output_path} ({block_count} блоков)")
