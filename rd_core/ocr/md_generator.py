"""Генератор Markdown (_document.md) из OCR результатов (оптимизирован для LLM)."""
import json as json_module
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .generator_common import (
    DATALAB_IMG_PATTERN,
    DATALAB_MD_IMG_PATTERN,
    collect_block_groups,
    collect_inheritable_stamp_data,
    extract_image_ocr_data,
    find_page_stamp,
    get_block_armor_id,
    is_image_ocr_json,
    sanitize_html,
    sanitize_markdown,
)

logger = logging.getLogger(__name__)


def _format_stamp_md(stamp_data: Dict) -> str:
    """Форматировать данные штампа в компактную Markdown строку."""
    parts = []

    if stamp_data.get("document_code"):
        parts.append(f"Шифр: {stamp_data['document_code']}")
    if stamp_data.get("stage"):
        parts.append(f"Стадия: {stamp_data['stage']}")
    if stamp_data.get("project_name"):
        parts.append(f"Объект: {stamp_data['project_name']}")
    if stamp_data.get("organization"):
        parts.append(f"Организация: {stamp_data['organization']}")

    return " | ".join(parts) if parts else ""


def _clean_cell_text(text: str) -> str:
    """Очистить текст ячейки таблицы - заменить переносы на пробелы."""
    text = re.sub(r'\s*\n\s*', ' ', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()


def _is_complex_table(table_html: str) -> bool:
    """Проверить, является ли таблица сложной (colspan/rowspan)."""
    return bool(re.search(r'(?:colspan|rowspan)\s*=\s*["\']?\d+', table_html, re.IGNORECASE))


def _table_to_csv(table_html: str) -> str:
    """Конвертировать сложную таблицу в CSV-подобный формат."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL)
    if not rows:
        return ""

    csv_lines = []
    for row in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.DOTALL)
        if cells:
            cleaned = [_clean_cell_text(re.sub(r"<[^>]+>", "", c)) for c in cells]
            cleaned = [c for c in cleaned if c]
            if cleaned:
                csv_lines.append("; ".join(cleaned))

    return "\n".join(csv_lines)


def _table_to_markdown(table_html: str) -> str:
    """Конвертировать таблицу HTML в Markdown."""
    if _is_complex_table(table_html):
        return _table_to_csv(table_html)

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL)
    if not rows:
        return ""

    md_rows = []
    max_cols = 0

    for i, row in enumerate(rows):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.DOTALL)
        if not cells:
            continue

        cleaned = []
        for c in cells:
            text = re.sub(r"<[^>]+>", "", c)
            text = _clean_cell_text(text)
            cleaned.append(text)

        max_cols = max(max_cols, len(cleaned))
        md_rows.append("| " + " | ".join(cleaned) + " |")

        if i == 0:
            md_rows.append("|" + "|".join(["---"] * len(cleaned)) + "|")

    return "\n".join(md_rows)


def _html_to_markdown(html: str) -> str:
    """Конвертировать HTML в компактный Markdown."""
    if not html:
        return ""

    # Сначала санитизируем HTML (удаляем мусорные img от datalab)
    text = sanitize_html(html)

    # Удаляем stamp-info блоки (уже в header)
    text = re.sub(r'<div class="stamp-info[^"]*">.*?</div>', "", text, flags=re.DOTALL)

    # Удаляем BLOCK маркеры (уже в header)
    text = re.sub(r"<p>BLOCK:\s*[A-Z0-9\-]+</p>", "", text)

    # Удаляем Created, Linked, Grouped (уже в header)
    text = re.sub(r"<p><b>Created:</b>[^<]*</p>", "", text)
    text = re.sub(r"<p><b>Linked block:</b>[^<]*</p>", "", text)
    text = re.sub(r"<p><b>Grouped blocks:</b>[^<]*</p>", "", text)

    # Удаляем ссылки на кроп изображения
    text = re.sub(r'<p><a[^>]*>.*?Открыть кроп изображения.*?</a></p>', "", text, flags=re.DOTALL)

    # Обрабатываем таблицы ПЕРЕД остальным HTML
    def process_table_match(match):
        return _table_to_markdown(match.group(0))

    text = re.sub(r"<table[^>]*>.*?</table>", process_table_match, text, flags=re.DOTALL)

    # Заголовки
    text = re.sub(r"<h1[^>]*>\s*(.*?)\s*</h1>", r"# \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h2[^>]*>\s*(.*?)\s*</h2>", r"## \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h3[^>]*>\s*(.*?)\s*</h3>", r"### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h4[^>]*>\s*(.*?)\s*</h4>", r"#### \1\n", text, flags=re.DOTALL)

    # Жирный и курсив
    text = re.sub(r"<b>\s*(.*?)\s*</b>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<strong>\s*(.*?)\s*</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<i>\s*(.*?)\s*</i>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<em>\s*(.*?)\s*</em>", r"*\1*", text, flags=re.DOTALL)

    # Код
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(r"<pre[^>]*>(.*?)</pre>", r"```\n\1\n```", text, flags=re.DOTALL)

    # Списки
    text = re.sub(r"<li>\s*(.*?)\s*</li>", r"- \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<[ou]l[^>]*>", "", text)
    text = re.sub(r"</[ou]l>", "", text)

    # Удаляем все img теги (уже обработаны в sanitize_html, но на всякий случай)
    text = re.sub(r'<img[^>]*/?>','', text)

    # Ссылки
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL)

    # Переносы строк
    text = re.sub(r"<br\s*/?>", "\n", text)

    # Параграфы
    text = re.sub(r"<p[^>]*>\s*(.*?)\s*</p>", r"\1\n", text, flags=re.DOTALL)

    # Удаляем оставшиеся HTML теги
    text = re.sub(r"<[^>]+>", "", text)

    # Декодируем HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")

    # Удаляем остаточные markdown-ссылки на мусорные изображения
    text = DATALAB_MD_IMG_PATTERN.sub("", text)

    # Нормализуем пробелы и переносы
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def _format_image_ocr_md(data: dict) -> str:
    """Форматировать данные OCR изображения в компактный Markdown."""
    img_data = extract_image_ocr_data(data)
    parts = []

    # Заголовок: [ИЗОБРАЖЕНИЕ] Тип: XXX | Оси: XXX
    header_parts = ["**[ИЗОБРАЖЕНИЕ]**"]
    if img_data.get("zone_name") and img_data["zone_name"] != "Не определено":
        header_parts.append(f"Тип: {img_data['zone_name']}")
    if img_data.get("grid_lines") and img_data["grid_lines"] != "Не определены":
        header_parts.append(f"Оси: {img_data['grid_lines']}")
    if img_data.get("location_text"):
        header_parts.append(img_data["location_text"])
    parts.append(" | ".join(header_parts))

    # Краткое описание
    if img_data.get("content_summary"):
        parts.append(f"**Краткое описание:** {img_data['content_summary']}")

    # Детальное описание
    if img_data.get("detailed_description"):
        parts.append(f"**Описание:** {img_data['detailed_description']}")

    # Распознанный текст
    if img_data.get("clean_ocr_text"):
        parts.append(f"**Текст на чертеже:** {img_data['clean_ocr_text']}")

    # Ключевые сущности - через запятую, без backticks
    if img_data.get("key_entities"):
        entities = ", ".join(img_data["key_entities"])
        parts.append(f"**Сущности:** {entities}")

    return "\n".join(parts) if parts else ""


def _process_ocr_content(ocr_text: str) -> str:
    """Обработать содержимое блока и конвертировать в Markdown."""
    if not ocr_text:
        return ""

    text = ocr_text.strip()
    if not text:
        return ""

    # HTML контент (включая случаи, начинающиеся с закрывающего тега)
    if text.startswith("<") or text.startswith("</"):
        return _html_to_markdown(text)

    # JSON контент
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json_module.loads(text)
            if isinstance(parsed, dict) and is_image_ocr_json(parsed):
                return _format_image_ocr_md(parsed)
            # Fallback для другого JSON
            return json_module.dumps(parsed, ensure_ascii=False, separators=(',', ':'))
        except json_module.JSONDecodeError:
            pass

    # Обычный текст - также применяем санитизацию markdown
    return sanitize_markdown(text)


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

        md_parts = []

        # === HEADER ===
        md_parts.append(f"# {title}")
        md_parts.append("")
        md_parts.append(f"Сгенерировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

        # Штамп документа
        if inherited_stamp_data:
            stamp_str = _format_stamp_md(inherited_stamp_data)
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

                block_count += 1
                armor_code = get_block_armor_id(block.id)
                block_type = block.block_type.value.upper()

                # Метаданные блока - компактно в одну строку
                meta_parts = [f"[{block_type}]", f"BLOCK:{armor_code}"]

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

                md_parts.append(" ".join(meta_parts))

                # Содержимое блока
                content = _process_ocr_content(block.ocr_text)
                if content:
                    md_parts.append(content)

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
        stamp_str = _format_stamp_md(first_stamp)
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
            block_type = blk.get("block_type", "text").upper()
            ocr_html = blk.get("ocr_html", "")
            ocr_text = blk.get("ocr_text", "")

            block_count += 1

            # Метаданные блока
            meta_parts = [f"[{block_type}]", f"BLOCK:{block_id}"]

            # Linked block
            if blk.get("linked_block_id"):
                meta_parts.append(f"→{blk['linked_block_id']}")

            # Grouped blocks
            group_id = blk.get("group_id")
            if group_id and group_id in groups:
                group_name = blk.get("group_name") or "группа"
                group_block_ids = groups[group_id]
                meta_parts.append(f"📦{group_name}[{','.join(group_block_ids)}]")

            md_parts.append(" ".join(meta_parts))

            # Содержимое блока
            content = ""
            if ocr_html:
                content = _html_to_markdown(ocr_html)
            elif ocr_text:
                content = _process_ocr_content(ocr_text)

            if content:
                md_parts.append(content)
            else:
                md_parts.append("*(нет данных)*")

            md_parts.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_parts))

    logger.info(f"MD регенерирован из result.json: {output_path} ({block_count} блоков)")
