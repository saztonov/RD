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
    build_linked_blocks_index,
    build_linked_blocks_index_dict,
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


def _parse_cell_span(cell_tag: str) -> tuple:
    """Извлечь colspan и rowspan из тега ячейки."""
    colspan_match = re.search(r'colspan\s*=\s*["\']?(\d+)', cell_tag, re.IGNORECASE)
    rowspan_match = re.search(r'rowspan\s*=\s*["\']?(\d+)', cell_tag, re.IGNORECASE)
    colspan = int(colspan_match.group(1)) if colspan_match else 1
    rowspan = int(rowspan_match.group(1)) if rowspan_match else 1
    return colspan, rowspan


def _table_to_markdown(table_html: str) -> str:
    """Конвертировать таблицу HTML в Markdown (включая сложные таблицы с colspan/rowspan)."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL)
    if not rows:
        return ""

    # Парсим все строки с учетом colspan/rowspan
    parsed_rows = []
    rowspan_tracker = {}  # {col_index: (remaining_rows, text)}

    for row_html in rows:
        # Находим все ячейки с их тегами
        cell_matches = re.findall(r"<(t[hd][^>]*)>(.*?)</t[hd]>", row_html, flags=re.DOTALL)
        if not cell_matches:
            continue

        row_cells = []
        col_idx = 0
        cell_iter = iter(cell_matches)

        while True:
            # Проверяем, есть ли активный rowspan для текущей колонки
            if col_idx in rowspan_tracker:
                remaining, text = rowspan_tracker[col_idx]
                row_cells.append("")  # Пустая ячейка для объединенной строки
                if remaining <= 1:
                    del rowspan_tracker[col_idx]
                else:
                    rowspan_tracker[col_idx] = (remaining - 1, text)
                col_idx += 1
                continue

            # Берем следующую ячейку из HTML
            try:
                cell_tag, cell_content = next(cell_iter)
            except StopIteration:
                break

            colspan, rowspan = _parse_cell_span(cell_tag)
            text = re.sub(r"<[^>]+>", "", cell_content)
            text = _clean_cell_text(text)

            # Добавляем ячейку
            row_cells.append(text)

            # Регистрируем rowspan для последующих строк
            if rowspan > 1:
                rowspan_tracker[col_idx] = (rowspan - 1, text)

            col_idx += 1

            # Добавляем пустые ячейки для colspan
            for _ in range(colspan - 1):
                row_cells.append("")
                col_idx += 1

        # Обрабатываем оставшиеся rowspan'ы в конце строки
        while col_idx in rowspan_tracker:
            remaining, text = rowspan_tracker[col_idx]
            row_cells.append("")
            if remaining <= 1:
                del rowspan_tracker[col_idx]
            else:
                rowspan_tracker[col_idx] = (remaining - 1, text)
            col_idx += 1

        if row_cells:
            parsed_rows.append(row_cells)

    if not parsed_rows:
        return ""

    # Определяем максимальное количество колонок
    max_cols = max(len(row) for row in parsed_rows)

    # Выравниваем все строки по максимальному количеству колонок
    for row in parsed_rows:
        while len(row) < max_cols:
            row.append("")

    # Формируем markdown таблицу
    md_rows = []
    for i, row in enumerate(parsed_rows):
        # Экранируем pipe в содержимом ячеек
        escaped_cells = [cell.replace("|", "\\|") for cell in row]
        md_rows.append("| " + " | ".join(escaped_cells) + " |")

        # Добавляем разделитель после первой строки (заголовок)
        if i == 0:
            md_rows.append("|" + "|".join(["---"] * max_cols) + "|")

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

    # Заголовки (сдвиг на 3 уровня вниз для вложенности в блок)
    text = re.sub(r"<h1[^>]*>\s*(.*?)\s*</h1>", r"#### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h2[^>]*>\s*(.*?)\s*</h2>", r"##### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h3[^>]*>\s*(.*?)\s*</h3>", r"###### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h4[^>]*>\s*(.*?)\s*</h4>", r"###### \1\n", text, flags=re.DOTALL)

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
    """Форматировать данные OCR изображения в компактный Markdown.

    Поддерживает два формата:
    1. Старый формат: content_summary, detailed_description, clean_ocr_text
    2. Новый формат: analysis.raw_text, personnel, axes, project_details
    """
    img_data = extract_image_ocr_data(data)
    parts = []

    # Новый формат: raw_text уже содержит готовый markdown
    if img_data.get("raw_text"):
        return img_data["raw_text"]

    # Новый формат: структурированные данные
    has_new_format = any(
        img_data.get(k) for k in ["organization", "personnel", "sheet_info", "project_details", "axes"]
    )

    if has_new_format:
        # Организация
        if img_data.get("organization"):
            parts.append(f"**Организация:** {img_data['organization']}")

        # Персонал
        if img_data.get("personnel"):
            personnel_lines = ["**Исполнители:**"]
            for person in img_data["personnel"]:
                if isinstance(person, dict):
                    role = person.get("role", "")
                    name = person.get("name", "")
                    date = person.get("date", "")
                    if role and name:
                        line = f"- {role}: {name}"
                        if date:
                            line += f" ({date})"
                        personnel_lines.append(line)
            if len(personnel_lines) > 1:
                parts.append("\n".join(personnel_lines))

        # Информация о листе
        if img_data.get("sheet_info"):
            si = img_data["sheet_info"]
            current = si.get("current_sheet", "")
            total = si.get("total_sheets", "")
            if current or total:
                parts.append(f"**Лист:** {current} из {total}")

        # Детали проекта
        if img_data.get("project_details"):
            pd = img_data["project_details"]
            if pd.get("main_object"):
                floors = pd.get("floors", "")
                obj_str = pd["main_object"]
                if floors:
                    obj_str += f" ({floors} эт.)"
                parts.append(f"**Объект:** {obj_str}")
            if pd.get("additional_structures"):
                structs = pd["additional_structures"]
                struct_strs = [f"{s.get('id', '')} ({s.get('floors', '')} эт.)" for s in structs if isinstance(s, dict)]
                if struct_strs:
                    parts.append(f"**Доп. строения:** {', '.join(struct_strs)}")

        # Оси
        if img_data.get("axes"):
            axes = img_data["axes"]
            axis_parts = []
            if axes.get("horizontal"):
                axis_parts.append(f"горизонтальные: {', '.join(str(a) for a in axes['horizontal'])}")
            if axes.get("vertical"):
                axis_parts.append(f"вертикальные: {', '.join(str(a) for a in axes['vertical'])}")
            if axis_parts:
                parts.append(f"**Оси:** {'; '.join(axis_parts)}")

        # Разрезы
        if img_data.get("sections"):
            sections = img_data["sections"]
            sect_strs = [f"{s.get('label', '')} ({s.get('orientation', '')})" for s in sections if isinstance(s, dict)]
            if sect_strs:
                parts.append(f"**Разрезы:** {', '.join(sect_strs)}")

        # Примечания
        if img_data.get("notes_fragment"):
            notes = img_data["notes_fragment"]
            if isinstance(notes, list):
                parts.append(f"**Примечания:** {'; '.join(notes)}")
            else:
                parts.append(f"**Примечания:** {notes}")

        # Сырой текст как fallback
        if not parts and img_data.get("raw_pdfplumber_text"):
            parts.append(f"**Текст:** {img_data['raw_pdfplumber_text']}")

        return "\n".join(parts) if parts else img_data.get("raw_pdfplumber_text", "")

    # Старый формат
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


def _format_generic_json_md(data: dict, max_depth: int = 3) -> str:
    """Универсальный fallback для форматирования любого JSON в Markdown.

    Рекурсивно извлекает текстовые значения из JSON и форматирует их.

    Args:
        data: JSON данные (dict или list)
        max_depth: максимальная глубина рекурсии

    Returns:
        Отформатированный текст
    """
    if max_depth <= 0:
        return ""

    parts = []

    def extract_text_values(obj, depth: int = 0, prefix: str = "") -> list:
        """Рекурсивно извлечь текстовые значения."""
        result = []
        if depth > max_depth:
            return result

        if isinstance(obj, dict):
            for key, value in obj.items():
                # Пропускаем служебные поля
                if key in ("doc_metadata", "image", "uri", "mime_type"):
                    continue

                if isinstance(value, str) and value.strip():
                    # Форматируем ключ
                    formatted_key = key.replace("_", " ").title()
                    result.append(f"**{formatted_key}:** {value.strip()}")
                elif isinstance(value, (dict, list)):
                    nested = extract_text_values(value, depth + 1, key)
                    result.extend(nested)
                elif isinstance(value, (int, float)) and key not in ("page",):
                    formatted_key = key.replace("_", " ").title()
                    result.append(f"**{formatted_key}:** {value}")

        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, str) and item.strip():
                    result.append(f"- {item.strip()}")
                elif isinstance(item, dict):
                    # Форматируем элемент списка
                    item_parts = []
                    for k, v in item.items():
                        if isinstance(v, str) and v.strip():
                            item_parts.append(f"{k}: {v}")
                    if item_parts:
                        result.append(f"- {', '.join(item_parts)}")

        return result

    parts = extract_text_values(data)

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
            if isinstance(parsed, dict):
                if is_image_ocr_json(parsed):
                    return _format_image_ocr_md(parsed)
                # Универсальный fallback для любого JSON
                formatted = _format_generic_json_md(parsed)
                if formatted:
                    return formatted
            elif isinstance(parsed, list):
                # Для списков тоже используем fallback
                formatted = _format_generic_json_md({"items": parsed})
                if formatted:
                    return formatted
            # Если ничего не извлеклось - возвращаем как есть (но не сырой JSON)
            return ""
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
                content = _process_ocr_content(block.ocr_text)
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
                content = _html_to_markdown(ocr_html)
            elif ocr_text:
                content = _process_ocr_content(ocr_text)

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
