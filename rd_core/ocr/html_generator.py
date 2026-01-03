"""Генератор HTML из OCR результатов"""
import json as json_module
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_block_armor_id(block_id: str) -> str:
    """
    Получить armor ID блока.

    Новые блоки уже имеют ID в формате XXXX-XXXX-XXX.
    Для legacy UUID блоков - конвертируем в armor формат.
    """
    # Если уже в armor формате (11 символов без дефисов, pattern XXXX-XXXX-XXX)
    clean = block_id.replace("-", "")
    if len(clean) == 11 and all(c in "34679ACDEFGHJKLMNPQRTUVWXY" for c in clean):
        return block_id  # Уже armor ID

    # Legacy: конвертируем UUID в armor формат
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


def _format_image_ocr_json(data: dict) -> str:
    """
    Форматировать JSON блока изображения в человекочитаемый HTML.

    Обрабатывает структуры с полями:
    - location, content_summary, detailed_description, clean_ocr_text, key_entities
    или с обёрткой "analysis"
    """
    # Если есть обёртка "analysis", извлекаем её
    if "analysis" in data and isinstance(data["analysis"], dict):
        data = data["analysis"]

    parts = []

    # Локация
    location = data.get("location")
    if location:
        parts.append("<h3>Расположение на чертеже</h3>")
        if isinstance(location, dict):
            if location.get("zone_name") and location["zone_name"] != "Не определено":
                parts.append(f"<p><b>Тип элемента:</b> {location['zone_name']}</p>")
            if location.get("grid_lines") and location["grid_lines"] != "Не определены":
                parts.append(
                    f"<p><b>Координатные оси:</b> {location['grid_lines']}</p>"
                )
        else:
            parts.append(f"<p>{location}</p>")

    # Краткое описание
    content_summary = data.get("content_summary")
    if content_summary:
        parts.append("<h3>Краткая характеристика</h3>")
        parts.append(f"<p>{content_summary}</p>")

    # Детальное описание
    detailed_desc = data.get("detailed_description")
    if detailed_desc:
        parts.append("<h3>Детальное описание графики</h3>")
        parts.append(f"<p>{detailed_desc}</p>")

    # Распознанный текст
    clean_ocr = data.get("clean_ocr_text")
    if clean_ocr:
        parts.append("<h3>Распознанный текст (clean_ocr_text)</h3>")
        # Форматируем текст с переносами строк
        formatted_text = clean_ocr.replace(" - ", "<br/>• ")
        if not formatted_text.startswith("<br/>"):
            formatted_text = "• " + formatted_text
        else:
            formatted_text = formatted_text[5:]  # убираем первый <br/>
        parts.append(f"<p style='line-height: 1.8;'>{formatted_text}</p>")

    # Ключевые сущности
    key_entities = data.get("key_entities")
    if key_entities and isinstance(key_entities, list):
        parts.append("<h3>Ключевые сущности (key_entities)</h3>")
        parts.append("<p style='line-height: 1.6;'>")
        # Группируем по 5 элементов в строку
        for i in range(0, len(key_entities), 5):
            batch = key_entities[i : i + 5]
            parts.append(
                "<code style='background: #e8f4f8; padding: 0.2rem 0.4rem; margin: 0.2rem; border-radius: 3px; display: inline-block;'>"
                + "</code> <code style='background: #e8f4f8; padding: 0.2rem 0.4rem; margin: 0.2rem; border-radius: 3px; display: inline-block;'>".join(
                    batch
                )
                + "</code>"
            )
            if i + 5 < len(key_entities):
                parts.append("<br/>")
        parts.append("</p>")

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

    # Если начинается с HTML тега - возвращаем как есть
    if text.startswith("<"):
        return text

    # Пробуем распарсить как JSON
    try:
        parsed = json_module.loads(text)

        # Проверяем, это JSON блока изображения?
        if isinstance(parsed, dict):
            # Проверяем наличие характерных полей image OCR
            has_image_fields = any(
                key in parsed or (parsed.get("analysis") and key in parsed["analysis"])
                for key in ["content_summary", "detailed_description", "clean_ocr_text"]
            )

            if has_image_fields:
                formatted = _format_image_ocr_json(parsed)
                if formatted:
                    return formatted

            # Иначе пробуем извлечь HTML из структуры
            html = _extract_html_from_parsed(parsed)
            if html:
                return html
    except json_module.JSONDecodeError:
        pass

    # Fallback: возвращаем как есть (экранируем HTML)
    return f"<pre>{_escape_html(text)}</pre>"


def _extract_html_from_parsed(data: Any) -> str:
    """Извлечь HTML из распарсенного JSON."""
    html_parts = []

    if isinstance(data, dict):
        # Если есть html на этом уровне
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


def _parse_stamp_json(ocr_text: Optional[str]) -> Optional[Dict]:
    """Извлечь JSON штампа из ocr_text."""
    if not ocr_text:
        return None

    text = ocr_text.strip()
    if not text:
        return None

    # Прямой JSON
    if text.startswith("{"):
        try:
            return json_module.loads(text)
        except json_module.JSONDecodeError:
            pass

    # JSON внутри ```json ... ```
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json_module.loads(json_match.group(1))
        except json_module.JSONDecodeError:
            pass

    return None


def _format_stamp_html(stamp_data: Dict) -> str:
    """Форматировать данные штампа в компактный HTML блок."""
    parts = []

    # Шифр
    if stamp_data.get("document_code"):
        parts.append(f"<b>Шифр:</b> {stamp_data['document_code']}")

    # Стадия
    if stamp_data.get("stage"):
        parts.append(f"<b>Стадия:</b> {stamp_data['stage']}")

    # Лист
    sheet_num = stamp_data.get("sheet_number", "")
    total = stamp_data.get("total_sheets", "")
    if sheet_num or total:
        parts.append(
            f"<b>Лист:</b> {sheet_num} (из {total})"
            if total
            else f"<b>Лист:</b> {sheet_num}"
        )

    # Объект
    if stamp_data.get("project_name"):
        parts.append(f"<b>Объект:</b> {stamp_data['project_name']}")

    # Наименование листа
    if stamp_data.get("sheet_name"):
        parts.append(f"<b>Наименование:</b> {stamp_data['sheet_name']}")

    # Организация
    if stamp_data.get("organization"):
        parts.append(f"<b>Организация:</b> {stamp_data['organization']}")

    # Ревизии/изменения
    revisions = stamp_data.get("revisions")
    if revisions:
        if isinstance(revisions, list) and revisions:
            # Берём последнюю ревизию
            last_rev = revisions[-1] if revisions else {}
            rev_num = last_rev.get("revision_number", "")
            doc_num = last_rev.get("document_number", "")
            rev_date = last_rev.get("date", "")
            if rev_num or doc_num:
                rev_str = f"Изм. {rev_num}"
                if doc_num:
                    rev_str += f" (Док. № {doc_num}"
                    if rev_date:
                        rev_str += f" от {rev_date}"
                    rev_str += ")"
                parts.append(f"<b>Статус:</b> {rev_str}")
        elif isinstance(revisions, str):
            parts.append(f"<b>Статус:</b> {revisions}")

    # Подписи
    signatures = stamp_data.get("signatures")
    if signatures:
        if isinstance(signatures, list):
            sig_parts = []
            for sig in signatures:
                if isinstance(sig, dict):
                    role = sig.get("role", "")
                    name = sig.get("name", "")
                    if role and name:
                        sig_parts.append(f"{role}: {name}")
                elif isinstance(sig, str):
                    sig_parts.append(sig)
            if sig_parts:
                parts.append(f"<b>Ответственные:</b> {'; '.join(sig_parts)}")
        elif isinstance(signatures, str):
            parts.append(f"<b>Ответственные:</b> {signatures}")

    if not parts:
        return ""

    return '<div class="stamp-info">' + " | ".join(parts) + "</div>"


def _find_page_stamp(blocks: List) -> Optional[Dict]:
    """Найти данные штампа на странице (из блока с category_code='stamp')."""
    for block in blocks:
        if getattr(block, "category_code", None) == "stamp":
            stamp_data = _parse_stamp_json(block.ocr_text)
            if stamp_data:
                return stamp_data
    return None


# Поля штампа, наследуемые на страницы без штампа
INHERITABLE_STAMP_FIELDS = ("document_code", "project_name", "stage", "organization")


def _collect_inheritable_stamp_data(pages: List) -> Optional[Dict]:
    """
    Собрать общие поля штампа со всех страниц.
    Для каждого поля выбирается наиболее часто встречающееся значение (мода).
    """
    from collections import Counter

    # Собираем все значения для каждого поля
    field_values: Dict[str, List] = {field: [] for field in INHERITABLE_STAMP_FIELDS}

    for page in pages:
        stamp_data = _find_page_stamp(page.blocks)
        if stamp_data:
            for field in INHERITABLE_STAMP_FIELDS:
                val = stamp_data.get(field)
                if val:  # непустое значение
                    field_values[field].append(val)

    # Выбираем моду для каждого поля
    inherited = {}
    for field in INHERITABLE_STAMP_FIELDS:
        values = field_values[field]
        if values:
            counter = Counter(values)
            most_common = counter.most_common(1)[0][0]
            inherited[field] = most_common

    return inherited if inherited else None


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
    Генерация итогового HTML файла из OCR результатов.

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

        html_parts = [
            f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - OCR</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 2rem; line-height: 1.6; }}
        .block {{ margin: 1.5rem 0; padding: 1rem; border-left: 3px solid #3498db; background: #f8f9fa; }}
        .block-header {{ font-size: 0.8rem; color: #666; margin-bottom: 0.5rem; }}
        .block-content {{ }}
        .block-type-text {{ border-left-color: #2ecc71; }}
        .block-type-table {{ border-left-color: #e74c3c; }}
        .block-type-image {{ border-left-color: #9b59b6; }}
        .block-content h3 {{ color: #555; font-size: 1rem; margin: 1rem 0 0.5rem 0; padding-bottom: 0.3rem; border-bottom: 1px solid #ddd; }}
        .block-content p {{ margin: 0.5rem 0; }}
        .block-content code {{ background: #e8f4f8; padding: 0.2rem 0.4rem; margin: 0.2rem; border-radius: 3px; display: inline-block; font-family: 'Consolas', 'Courier New', monospace; font-size: 0.9em; }}
        .stamp-info {{ font-size: 0.75rem; color: #2980b9; background: #eef6fc; padding: 0.4rem 0.6rem; margin-top: 0.5rem; border-radius: 3px; border: 1px solid #bde0f7; }}
        .stamp-inherited {{ color: #7f8c8d; background: #f5f5f5; border-color: #ddd; font-style: italic; }}
        table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0; }}
        th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
        th {{ background: #f0f0f0; }}
        img {{ max-width: 100%; height: auto; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; }}
        pre {{ white-space: pre-wrap; word-wrap: break-word; background: #fff; padding: 0.5rem; }}
    </style>
</head>
<body>
<h1>{title}</h1>
<p>Сгенерировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
"""
        ]

        # Собираем блоки по группам для отображения групповой информации
        groups: Dict[str, List] = {}  # group_id -> list of blocks
        all_blocks: Dict[str, Any] = {}  # block_id -> block
        for page in pages:
            for block in page.blocks:
                all_blocks[block.id] = block
                group_id = getattr(block, "group_id", None)
                if group_id:
                    if group_id not in groups:
                        groups[group_id] = []
                    groups[group_id].append(block)

        # Собираем общие данные штампа для страниц без штампа
        inherited_stamp_data = _collect_inheritable_stamp_data(pages)
        inherited_stamp_html = (
            _format_inherited_stamp_html(inherited_stamp_data)
            if inherited_stamp_data
            else ""
        )

        block_count = 0
        for page in pages:
            # Находим данные штампа для этой страницы
            page_stamp = _find_page_stamp(page.blocks)
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
                # Пропускаем блоки штампа - их данные уже добавлены в stamp_html каждого блока
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

                # Вставляем маркер BLOCK: XXXX-XXXX-XXX для ocr_result_merger
                armor_code = _get_block_armor_id(block.id)
                html_parts.append(f"<p>BLOCK: {armor_code}</p>")

                # Grouped blocks: группа и все блоки в ней
                group_id = getattr(block, "group_id", None)
                if group_id and group_id in groups:
                    group_name = getattr(block, "group_name", None) or group_id
                    group_block_ids = [
                        _get_block_armor_id(b.id) for b in groups[group_id]
                    ]
                    html_parts.append(
                        f'<p><b>Grouped blocks:</b> {group_name} [{", ".join(group_block_ids)}]</p>'
                    )

                # Linked block: связанный блок
                linked_id = getattr(block, "linked_block_id", None)
                if linked_id:
                    linked_armor = _get_block_armor_id(linked_id)
                    html_parts.append(f"<p><b>Linked block:</b> {linked_armor}</p>")

                # Created at: дата создания блока
                created_at = getattr(block, "created_at", None)
                if created_at:
                    html_parts.append(f"<p><b>Created:</b> {created_at}</p>")

                # Добавляем информацию о штампе сразу после маркера блока (в метаинформацию)
                if stamp_html:
                    html_parts.append(stamp_html)

                # Для IMAGE блоков добавляем ссылку на изображение в начале
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

        html_parts.append("</body></html>")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))

        logger.info(f"HTML файл сохранён: {output_file} ({block_count} блоков)")
        return str(output_file)

    except Exception as e:
        logger.error(f"Ошибка генерации HTML: {e}", exc_info=True)
        raise
