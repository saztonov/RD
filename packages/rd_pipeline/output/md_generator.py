"""Генератор Markdown (_document.md) из OCR результатов (оптимизирован для LLM)."""
import logging
from datetime import datetime
from pathlib import Path
from typing import List

from rd_pipeline.common import (
    build_linked_blocks_index,
    collect_block_groups,
    collect_inheritable_stamp_data,
    find_page_stamp,
    get_block_armor_id,
)
from rd_pipeline.output.md_formatters import (
    format_stamp_md,
    process_ocr_content,
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
