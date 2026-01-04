"""Генератор Markdown из OCR результатов (оптимизирован для LLM)"""
import json as json_module
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Поля штампа, наследуемые на страницы без штампа
INHERITABLE_STAMP_FIELDS = ("document_code", "project_name", "stage", "organization")


def _get_block_armor_id(block_id: str) -> str:
    """Получить armor ID блока."""
    clean = block_id.replace("-", "")
    if len(clean) == 11 and all(c in "34679ACDEFGHJKLMNPQRTUVWXY" for c in clean):
        return block_id

    ALPHABET = "34679ACDEFGHJKLMNPQRTUVWXY"

    def num_to_base26(num: int, length: int) -> str:
        if num == 0:
            return ALPHABET[0] * length
        result = []
        while num > 0:
            result.append(ALPHABET[num % 26])
            num //= 26
        while len(result) < length:
            result.append(ALPHABET[0])
        return "".join(reversed(result[-length:]))

    def calculate_checksum(payload: str) -> str:
        char_map = {c: i for i, c in enumerate(ALPHABET)}
        v1, v2, v3 = 0, 0, 0
        for i, char in enumerate(payload):
            val = char_map.get(char, 0)
            v1 += val
            v2 += val * (i + 3)
            v3 += val * (i + 7) * (i + 1)
        return ALPHABET[v1 % 26] + ALPHABET[v2 % 26] + ALPHABET[v3 % 26]

    clean = block_id.replace("-", "").lower()
    hex_prefix = clean[:10]
    num = int(hex_prefix, 16)
    payload = num_to_base26(num, 8)
    checksum = calculate_checksum(payload)
    full_code = payload + checksum
    return f"{full_code[:4]}-{full_code[4:8]}-{full_code[8:]}"


def _parse_stamp_json(ocr_text: Optional[str]) -> Optional[Dict]:
    """Извлечь JSON штампа из ocr_text."""
    if not ocr_text:
        return None

    text = ocr_text.strip()
    if not text:
        return None

    if text.startswith("{"):
        try:
            return json_module.loads(text)
        except json_module.JSONDecodeError:
            pass

    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json_module.loads(json_match.group(1))
        except json_module.JSONDecodeError:
            pass

    return None


def _find_page_stamp(blocks: List) -> Optional[Dict]:
    """Найти данные штампа на странице."""
    for block in blocks:
        if getattr(block, "category_code", None) == "stamp":
            stamp_data = _parse_stamp_json(block.ocr_text)
            if stamp_data:
                return stamp_data
    return None


def _collect_inheritable_stamp_data(pages: List) -> Optional[Dict]:
    """Собрать общие поля штампа со всех страниц."""
    from collections import Counter

    field_values: Dict[str, List] = {field: [] for field in INHERITABLE_STAMP_FIELDS}

    for page in pages:
        stamp_data = _find_page_stamp(page.blocks)
        if stamp_data:
            for field in INHERITABLE_STAMP_FIELDS:
                val = stamp_data.get(field)
                if val:
                    field_values[field].append(val)

    inherited = {}
    for field in INHERITABLE_STAMP_FIELDS:
        values = field_values[field]
        if values:
            counter = Counter(values)
            most_common = counter.most_common(1)[0][0]
            inherited[field] = most_common

    return inherited if inherited else None


def _format_stamp_md(stamp_data: Dict) -> str:
    """Форматировать данные штампа в компактную строку."""
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
    # Заменяем переносы строк на пробелы
    text = re.sub(r'\s*\n\s*', ' ', text)
    # Убираем множественные пробелы
    text = re.sub(r' +', ' ', text)
    # Убираем пробелы по краям
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
            # Фильтруем пустые
            cleaned = [c for c in cleaned if c]
            if cleaned:
                csv_lines.append("; ".join(cleaned))

    return "\n".join(csv_lines)


def _table_to_markdown(table_html: str) -> str:
    """Конвертировать таблицу HTML в Markdown."""
    # Проверяем на сложную таблицу
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

        # Очищаем ячейки: убираем HTML и переносы
        cleaned = []
        for c in cells:
            text = re.sub(r"<[^>]+>", "", c)
            text = _clean_cell_text(text)
            cleaned.append(text)

        max_cols = max(max_cols, len(cleaned))
        md_rows.append("| " + " | ".join(cleaned) + " |")

        # Добавляем разделитель после первой строки
        if i == 0:
            md_rows.append("|" + "|".join(["---"] * len(cleaned)) + "|")

    return "\n".join(md_rows)


def _html_to_markdown(html: str) -> str:
    """Конвертировать HTML в компактный Markdown."""
    if not html:
        return ""

    text = html

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

    # Заголовки - компактно
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

    # Изображения - компактно
    text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*/?>',
                  lambda m: f"[img:{Path(m.group(1)).stem}]" if m.group(1) else "", text)

    # Ссылки
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL)

    # Переносы строк
    text = re.sub(r"<br\s*/?>", "\n", text)

    # Параграфы - убираем теги, оставляем текст
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

    # Нормализуем пробелы и переносы
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def _format_json_content_compact(data: Any) -> str:
    """Форматировать JSON контент в компактный Markdown (для crops)."""
    if isinstance(data, dict):
        # Проверяем на image OCR структуру
        if "analysis" in data and isinstance(data["analysis"], dict):
            data = data["analysis"]

        parts = []

        # Локация - одной строкой
        location = data.get("location")
        if location:
            if isinstance(location, dict):
                zone = location.get("zone_name", "")
                grid = location.get("grid_lines", "")
                loc_parts = []
                if zone and zone != "Не определено":
                    loc_parts.append(zone)
                if grid and grid != "Не определены":
                    loc_parts.append(f"оси {grid}")
                if loc_parts:
                    parts.append(f"**Расположение:** {', '.join(loc_parts)}")
            elif location:
                parts.append(f"**Расположение:** {location}")

        # Краткое описание
        if data.get("content_summary"):
            parts.append(data["content_summary"])

        # Распознанный текст - убираем "•" маркеры
        if data.get("clean_ocr_text"):
            clean_text = data["clean_ocr_text"]
            clean_text = re.sub(r"•\s*", "", clean_text)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            if clean_text:
                parts.append(f"**Текст:** {clean_text}")

        # Ключевые сущности - компактно через запятую
        if data.get("key_entities") and isinstance(data["key_entities"], list):
            entities = ", ".join(data["key_entities"][:15])  # Максимум 15
            parts.append(f"**Сущности:** {entities}")

        if parts:
            return " | ".join(parts)

    # Fallback: компактный JSON
    return json_module.dumps(data, ensure_ascii=False, separators=(',', ':'))


def generate_md_from_pages(
    pages: List,
    output_path: str,
    doc_name: str = None,
    project_name: str = None,
) -> str:
    """
    Генерация компактного Markdown файла из OCR результатов.
    Группировка по страницам, оптимизация для LLM.
    """
    try:
        from rd_core.models import BlockType

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        title = doc_name or "OCR Result"

        # Собираем блоки по группам
        groups: Dict[str, List] = {}
        for page in pages:
            for block in page.blocks:
                group_id = getattr(block, "group_id", None)
                if group_id:
                    if group_id not in groups:
                        groups[group_id] = []
                    groups[group_id].append(block)

        # Собираем данные штампа
        inherited_stamp_data = _collect_inheritable_stamp_data(pages)

        md_parts = []

        # === HEADER ===
        md_parts.append(f"# {title}")
        md_parts.append("")
        md_parts.append(f"Сгенерировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

        # Штамп документа - компактно
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
                md_parts.append("")

            for block in page.blocks:
                # Пропускаем блоки штампа
                if getattr(block, "category_code", None) == "stamp":
                    continue

                block_count += 1
                armor_code = _get_block_armor_id(block.id)
                block_type = block.block_type.value.upper()

                # Метаданные блока - компактно в одну строку
                meta_parts = [f"[{block_type}]", f"BLOCK:{armor_code}"]

                # Linked block
                linked_id = getattr(block, "linked_block_id", None)
                if linked_id:
                    meta_parts.append(f"→{_get_block_armor_id(linked_id)}")

                # Grouped blocks
                group_id = getattr(block, "group_id", None)
                if group_id and group_id in groups:
                    group_name = getattr(block, "group_name", None) or "группа"
                    group_block_ids = [_get_block_armor_id(b.id) for b in groups[group_id]]
                    meta_parts.append(f"📦{group_name}[{','.join(group_block_ids)}]")

                md_parts.append(" ".join(meta_parts))

                # Содержимое блока
                ocr_text = block.ocr_text
                if ocr_text:
                    text = ocr_text.strip()
                    if text.startswith("<"):
                        # HTML контент
                        content = _html_to_markdown(text)
                    elif text.startswith("{") or text.startswith("["):
                        # JSON контент (crops)
                        try:
                            parsed = json_module.loads(text)
                            content = _format_json_content_compact(parsed)
                        except json_module.JSONDecodeError:
                            content = text
                    else:
                        content = text

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
    Группировка по страницам, проверка всех блоков из annotation.
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

            # Метаданные блока - компактно
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
                # Fallback: используем ocr_text напрямую
                text = ocr_text.strip()
                if text.startswith("<"):
                    content = _html_to_markdown(text)
                elif text.startswith("{") or text.startswith("["):
                    try:
                        parsed = json_module.loads(text)
                        content = _format_json_content_compact(parsed)
                    except json_module.JSONDecodeError:
                        content = text
                else:
                    content = text

            if content:
                md_parts.append(content)
            else:
                md_parts.append("*(нет данных)*")

            md_parts.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_parts))

    logger.info(f"MD регенерирован из result.json: {output_path} ({block_count} блоков)")
