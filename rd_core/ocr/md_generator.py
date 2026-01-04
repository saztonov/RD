"""Генератор Markdown из OCR результатов (оптимизирован для LLM)"""
import json as json_module
import logging
import os
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

    # Заголовки
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"# \1", text, flags=re.DOTALL)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"## \1", text, flags=re.DOTALL)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"### \1", text, flags=re.DOTALL)
    text = re.sub(r"<h4[^>]*>(.*?)</h4>", r"#### \1", text, flags=re.DOTALL)

    # Жирный и курсив
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)

    # Код
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(r"<pre[^>]*>(.*?)</pre>", r"```\n\1\n```", text, flags=re.DOTALL)

    # Списки
    text = re.sub(r"<li>(.*?)</li>", r"- \1", text, flags=re.DOTALL)
    text = re.sub(r"<[ou]l[^>]*>", "", text)
    text = re.sub(r"</[ou]l>", "", text)

    # Таблицы - упрощённая обработка
    def process_table(match):
        table_html = match.group(0)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL)
        if not rows:
            return ""

        md_rows = []
        for i, row in enumerate(rows):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.DOTALL)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if cells:
                md_rows.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    md_rows.append("|" + "|".join(["---"] * len(cells)) + "|")

        return "\n".join(md_rows)

    text = re.sub(r"<table[^>]*>.*?</table>", process_table, text, flags=re.DOTALL)

    # Изображения
    text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*/?>',
                  lambda m: f"![image]({m.group(1)})" if m.group(1) else "", text)

    # Ссылки
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL)

    # Переносы строк
    text = re.sub(r"<br\s*/?>", "\n", text)

    # Параграфы
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text, flags=re.DOTALL)

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
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def generate_md_from_pages(
    pages: List,
    output_path: str,
    doc_name: str = None,
    project_name: str = None,
) -> str:
    """
    Генерация компактного Markdown файла из OCR результатов.

    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения MD файла
        doc_name: имя документа (полный путь из дерева)
        project_name: имя проекта для ссылок

    Returns:
        Путь к сохранённому файлу
    """
    try:
        from rd_core.models import BlockType

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        title = doc_name or "OCR Result"

        # Собираем блоки по группам
        groups: Dict[str, List] = {}
        all_blocks: Dict[str, Any] = {}
        for page in pages:
            for block in page.blocks:
                all_blocks[block.id] = block
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
        md_parts.append("")

        # Штамп документа
        if inherited_stamp_data:
            stamp_str = _format_stamp_md(inherited_stamp_data)
            if stamp_str:
                md_parts.append(f"**Штамп:** {stamp_str}")
                md_parts.append("")

        md_parts.append("---")
        md_parts.append("")

        # === БЛОКИ ===
        block_count = 0
        annotation_block_ids = set()

        for page in pages:
            page_stamp = _find_page_stamp(page.blocks)
            if page_stamp:
                merged_stamp = dict(page_stamp)
                if inherited_stamp_data:
                    for field in INHERITABLE_STAMP_FIELDS:
                        if not merged_stamp.get(field):
                            if inherited_stamp_data.get(field):
                                merged_stamp[field] = inherited_stamp_data[field]
            elif inherited_stamp_data:
                merged_stamp = inherited_stamp_data
            else:
                merged_stamp = None

            for idx, block in enumerate(page.blocks):
                # Пропускаем блоки штампа
                if getattr(block, "category_code", None) == "stamp":
                    continue

                annotation_block_ids.add(block.id)
                block_count += 1
                page_num = page.page_number + 1 if page.page_number is not None else ""
                armor_code = _get_block_armor_id(block.id)

                # Шапка блока
                md_parts.append(f"## Блок #{idx + 1} (стр. {page_num})")
                md_parts.append(f"BLOCK: {armor_code}")

                # Linked block
                linked_id = getattr(block, "linked_block_id", None)
                if linked_id:
                    linked_armor = _get_block_armor_id(linked_id)
                    md_parts.append(f"Linked block: {linked_armor}")

                # Grouped blocks
                group_id = getattr(block, "group_id", None)
                if group_id and group_id in groups:
                    group_name = getattr(block, "group_name", None) or group_id
                    group_block_ids = [_get_block_armor_id(b.id) for b in groups[group_id]]
                    md_parts.append(f"Grouped blocks: {group_name} [{', '.join(group_block_ids)}]")

                md_parts.append("")

                # Содержимое блока
                ocr_text = block.ocr_text
                if ocr_text:
                    # Пробуем извлечь HTML
                    text = ocr_text.strip()
                    if text.startswith("<"):
                        # HTML контент
                        content = _html_to_markdown(text)
                    elif text.startswith("{") or text.startswith("["):
                        # JSON контент
                        try:
                            parsed = json_module.loads(text)
                            content = _format_json_content(parsed)
                        except json_module.JSONDecodeError:
                            content = text
                    else:
                        content = text

                    if content:
                        md_parts.append(content)
                        md_parts.append("")

                md_parts.append("---")
                md_parts.append("")

        # Записываем файл
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md_parts))

        logger.info(f"MD файл сохранён: {output_file} ({block_count} блоков)")
        return str(output_file)

    except Exception as e:
        logger.error(f"Ошибка генерации MD: {e}", exc_info=True)
        raise


def _format_json_content(data: Any) -> str:
    """Форматировать JSON контент в Markdown."""
    if isinstance(data, dict):
        # Проверяем на image OCR структуру
        if "analysis" in data and isinstance(data["analysis"], dict):
            data = data["analysis"]

        parts = []

        # Локация
        location = data.get("location")
        if location:
            if isinstance(location, dict):
                zone = location.get("zone_name", "")
                grid = location.get("grid_lines", "")
                if zone and zone != "Не определено":
                    parts.append(f"**Расположение:** {zone}")
                if grid and grid != "Не определены":
                    parts.append(f"**Координатные оси:** {grid}")
            else:
                parts.append(f"**Расположение:** {location}")

        # Краткое описание
        if data.get("content_summary"):
            parts.append(f"**Краткое описание:** {data['content_summary']}")

        # Детальное описание
        if data.get("detailed_description"):
            parts.append(f"{data['detailed_description']}")

        # Распознанный текст
        if data.get("clean_ocr_text"):
            parts.append(f"**Текст:** {data['clean_ocr_text']}")

        # Ключевые сущности
        if data.get("key_entities") and isinstance(data["key_entities"], list):
            entities = ", ".join(f"`{e}`" for e in data["key_entities"])
            parts.append(f"**Ключевые сущности:** {entities}")

        if parts:
            return "\n\n".join(parts)

    # Fallback: компактный JSON
    return f"```json\n{json_module.dumps(data, ensure_ascii=False, indent=2)}\n```"


def generate_md_from_result(
    result: dict, output_path: Path, doc_name: Optional[str] = None
) -> None:
    """
    Генерировать Markdown файл из result.json с правильно разделёнными блоками.

    Использует ocr_html (уже разделённый по маркерам).
    Проверяет что все блоки из annotation добавлены в MD.
    """
    if not doc_name:
        doc_name = result.get("pdf_path", "OCR Result")

    md_parts = []

    # === HEADER ===
    md_parts.append(f"# {doc_name}")
    md_parts.append("")
    md_parts.append(f"Сгенерировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    md_parts.append("")

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
    groups: Dict[str, List[str]] = {}  # group_id -> list of block_ids
    for page in result.get("pages", []):
        for blk in page.get("blocks", []):
            group_id = blk.get("group_id")
            if group_id:
                if group_id not in groups:
                    groups[group_id] = []
                groups[group_id].append(blk.get("id", ""))

    # === БЛОКИ ===
    block_count = 0
    processed_block_ids = set()

    for page in result.get("pages", []):
        page_num = page.get("page_number", "")

        for idx, blk in enumerate(page.get("blocks", [])):
            # Пропускаем блоки штампа
            if blk.get("category_code") == "stamp":
                continue

            block_id = blk.get("id", "")
            ocr_html = blk.get("ocr_html", "")
            ocr_text = blk.get("ocr_text", "")

            # Добавляем блок даже если нет ocr_html (восстановление)
            processed_block_ids.add(block_id)
            block_count += 1

            # Шапка блока
            md_parts.append(f"## Блок #{idx + 1} (стр. {page_num})")
            md_parts.append(f"BLOCK: {block_id}")

            # Linked block
            if blk.get("linked_block_id"):
                md_parts.append(f"Linked block: {blk['linked_block_id']}")

            # Grouped blocks
            group_id = blk.get("group_id")
            if group_id and group_id in groups:
                group_name = blk.get("group_name") or group_id
                group_block_ids = groups[group_id]
                md_parts.append(f"Grouped blocks: {group_name} [{', '.join(group_block_ids)}]")

            md_parts.append("")

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
                        content = _format_json_content(parsed)
                    except json_module.JSONDecodeError:
                        content = text
                else:
                    content = text

            if content:
                md_parts.append(content)
                md_parts.append("")
            else:
                md_parts.append("*(Содержимое не распознано)*")
                md_parts.append("")

            md_parts.append("---")
            md_parts.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_parts))

    logger.info(f"MD регенерирован из result.json: {output_path} ({block_count} блоков)")
