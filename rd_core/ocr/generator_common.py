"""Общие утилиты для генераторов HTML, Markdown и result.json из OCR результатов."""
import json as json_module
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union

from rd_core.models.armor_id import is_armor_id, uuid_to_armor_id

logger = logging.getLogger(__name__)

# Поля штампа, наследуемые на страницы без штампа
INHERITABLE_STAMP_FIELDS = ("document_code", "project_name", "stage", "organization")

# HTML шаблон (общий для всех генераторов)
HTML_TEMPLATE = """<!DOCTYPE html>
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
<p>Сгенерировано: {timestamp} UTC</p>
"""

HTML_FOOTER = "</body></html>"


def get_html_header(title: str) -> str:
    """Получить HTML заголовок с шаблоном."""
    return HTML_TEMPLATE.format(
        title=title,
        timestamp=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    )


def get_block_armor_id(block_id: str) -> str:
    """
    Получить armor ID блока.

    Новые блоки уже имеют ID в формате XXXX-XXXX-XXX.
    Для legacy UUID блоков - конвертируем в armor формат.
    """
    if is_armor_id(block_id):
        return block_id
    return uuid_to_armor_id(block_id)


def parse_stamp_json(ocr_text: Optional[str]) -> Optional[Dict]:
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


def find_page_stamp(blocks: List) -> Optional[Dict]:
    """Найти данные штампа на странице (из блока с category_code='stamp')."""
    for block in blocks:
        if getattr(block, "category_code", None) == "stamp":
            stamp_data = parse_stamp_json(block.ocr_text)
            if stamp_data:
                return stamp_data
    return None


def collect_inheritable_stamp_data(pages: List) -> Optional[Dict]:
    """
    Собрать общие поля штампа со всех страниц.
    Для каждого поля выбирается наиболее часто встречающееся значение (мода).
    """
    field_values: Dict[str, List] = {field: [] for field in INHERITABLE_STAMP_FIELDS}

    for page in pages:
        stamp_data = find_page_stamp(page.blocks)
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


def collect_block_groups(pages: List) -> Dict[str, List]:
    """Собрать блоки по группам."""
    groups: Dict[str, List] = {}
    for page in pages:
        for block in page.blocks:
            group_id = getattr(block, "group_id", None)
            if group_id:
                if group_id not in groups:
                    groups[group_id] = []
                groups[group_id].append(block)
    return groups


# Паттерн для мусорных img тегов от datalab (хеш_img.ext)
DATALAB_IMG_PATTERN = re.compile(
    r'<img[^>]*src=["\']?[a-f0-9]{20,}_img(?:\.[a-z]{3,4})?["\']?[^>]*/?>',
    re.IGNORECASE
)

# Паттерн для markdown-ссылок на мусорные изображения [img:hash_img]
DATALAB_MD_IMG_PATTERN = re.compile(r'\[img:[a-f0-9]{20,}_img\]')


def sanitize_html(html: str) -> str:
    """
    Очистить HTML от артефактов datalab OCR.

    1. Удаляет мусорные img теги (хеш_img.jpg)
    2. Удаляет осиротевшие закрывающие теги в начале
    3. Удаляет незакрытые открывающие теги в конце
    4. Удаляет вложенные DOCTYPE/html/body артефакты
    5. Удаляет закрывающие </p> без соответствующего открывающего <p>
    """
    if not html:
        return ""

    text = html

    # 1. Удаляем мусорные img теги от datalab
    text = DATALAB_IMG_PATTERN.sub("", text)

    # 2. Удаляем вложенные DOCTYPE/html/head/body артефакты (бывает внутри блоков)
    text = re.sub(r'<!DOCTYPE\s+html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</html\s*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head[^>]*>.*?</head\s*>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<body[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</body\s*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<div\s+class="page"[^>]*>', '', text, flags=re.IGNORECASE)

    # 3. Удаляем осиротевшие закрывающие теги в начале (могут повторяться)
    while True:
        new_text = re.sub(r'^\s*</[a-z]+>\s*', '', text, flags=re.IGNORECASE)
        if new_text == text:
            break
        text = new_text

    # 4. Удаляем незакрытые открывающие теги в конце
    text = re.sub(r'\s*<p>\s*$', '', text)
    text = re.sub(r'\s*<div[^>]*>\s*$', '', text)

    # 5. Удаляем "висячие" </p> теги - те, которым не предшествует <p>
    # Используем итеративный подход: разбиваем на части по </p> и проверяем баланс
    def remove_orphan_closing_p(html_text: str) -> str:
        """Удалить </p> теги без соответствующего <p>."""
        result = []
        parts = re.split(r'(</p>)', html_text, flags=re.IGNORECASE)
        open_count = 0

        for part in parts:
            if re.match(r'</p>', part, re.IGNORECASE):
                if open_count > 0:
                    result.append(part)
                    open_count -= 1
                # else: пропускаем "висячий" </p>
            else:
                # Считаем открывающие <p> в этой части
                open_count += len(re.findall(r'<p\b[^>]*>', part, re.IGNORECASE))
                result.append(part)

        return ''.join(result)

    text = remove_orphan_closing_p(text)

    # 6. Удаляем незакрытые <p> в конце
    # Проверяем баланс и удаляем последние <p> если они не закрыты
    while True:
        open_p = len(re.findall(r'<p\b[^>]*>', text, re.IGNORECASE))
        close_p = len(re.findall(r'</p>', text, re.IGNORECASE))
        if open_p <= close_p:
            break
        # Удаляем последний незакрытый <p>
        text = re.sub(r'<p\b[^>]*>(?!.*<p\b)', '', text, flags=re.DOTALL | re.IGNORECASE)

    # 7. Удаляем пустые теги
    text = re.sub(r'<p>\s*</p>', '', text, flags=re.IGNORECASE)

    # 8. Нормализуем множественные пустые строки
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def sanitize_markdown(md: str) -> str:
    """
    Очистить Markdown от артефактов datalab OCR.

    Удаляет ссылки вида [img:hash_img].
    """
    if not md:
        return ""

    # Удаляем мусорные markdown-ссылки на изображения
    text = DATALAB_MD_IMG_PATTERN.sub("", md)

    # Удаляем пустые строки после удаления
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def extract_image_ocr_data(data: dict) -> Dict[str, Any]:
    """
    Извлечь структурированные данные из JSON блока изображения.

    Returns:
        dict с полями: location, zone_name, grid_lines, content_summary,
        detailed_description, clean_ocr_text, key_entities
    """
    # Если есть обёртка "analysis", извлекаем её
    if "analysis" in data and isinstance(data["analysis"], dict):
        data = data["analysis"]

    result = {}

    # Локация
    location = data.get("location")
    if location:
        if isinstance(location, dict):
            result["zone_name"] = location.get("zone_name", "")
            result["grid_lines"] = location.get("grid_lines", "")
        else:
            result["location_text"] = str(location)

    # Описания
    result["content_summary"] = data.get("content_summary", "")
    result["detailed_description"] = data.get("detailed_description", "")

    # Распознанный текст - нормализуем
    clean_ocr = data.get("clean_ocr_text", "")
    if clean_ocr:
        clean_ocr = re.sub(r"•\s*", "", clean_ocr)
        clean_ocr = re.sub(r"\s+", " ", clean_ocr).strip()
    result["clean_ocr_text"] = clean_ocr

    # Ключевые сущности
    key_entities = data.get("key_entities", [])
    if isinstance(key_entities, list):
        result["key_entities"] = key_entities[:20]  # Максимум 20
    else:
        result["key_entities"] = []

    return result


def is_image_ocr_json(data: dict) -> bool:
    """Проверить, является ли JSON данными OCR изображения."""
    if not isinstance(data, dict):
        return False

    # Проверяем характерные поля
    image_fields = ["content_summary", "detailed_description", "clean_ocr_text"]
    return any(
        key in data or (data.get("analysis") and key in data["analysis"])
        for key in image_fields
    )


def format_stamp_parts(stamp_data: Dict) -> List[tuple]:
    """
    Извлечь части штампа для форматирования.

    Returns:
        Список кортежей (ключ, значение) для форматирования.
    """
    parts = []

    if stamp_data.get("document_code"):
        parts.append(("Шифр", stamp_data["document_code"]))
    if stamp_data.get("stage"):
        parts.append(("Стадия", stamp_data["stage"]))

    # Лист
    sheet_num = stamp_data.get("sheet_number", "")
    total = stamp_data.get("total_sheets", "")
    if sheet_num or total:
        sheet_str = f"{sheet_num} (из {total})" if total else str(sheet_num)
        parts.append(("Лист", sheet_str))

    if stamp_data.get("project_name"):
        parts.append(("Объект", stamp_data["project_name"]))
    if stamp_data.get("sheet_name"):
        parts.append(("Наименование", stamp_data["sheet_name"]))
    if stamp_data.get("organization"):
        parts.append(("Организация", stamp_data["organization"]))

    # Ревизии/изменения
    revisions = stamp_data.get("revisions")
    if revisions:
        if isinstance(revisions, list) and revisions:
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
                parts.append(("Статус", rev_str))
        elif isinstance(revisions, str):
            parts.append(("Статус", revisions))

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
                parts.append(("Ответственные", "; ".join(sig_parts)))
        elif isinstance(signatures, str):
            parts.append(("Ответственные", signatures))

    return parts


# =============================================================================
# Функции для работы с dict (используются в result.json / ocr_result_merger)
# =============================================================================


def find_page_stamp_dict(page: Dict) -> Optional[Dict]:
    """Найти JSON штампа на странице (для dict структуры)."""
    for blk in page.get("blocks", []):
        if blk.get("block_type") == "image" and blk.get("category_code") == "stamp":
            return blk.get("ocr_json")
    return None


def collect_inheritable_stamp_data_dict(pages: List[Dict]) -> Optional[Dict]:
    """
    Собрать общие поля штампа со всех страниц (для dict структуры).
    Для каждого поля выбирается наиболее часто встречающееся значение (мода).
    """
    field_values: Dict[str, List] = {field: [] for field in INHERITABLE_STAMP_FIELDS}

    for page in pages:
        stamp_json = find_page_stamp_dict(page)
        if stamp_json:
            for field in INHERITABLE_STAMP_FIELDS:
                val = stamp_json.get(field)
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


def propagate_stamp_data(page: Dict, inherited_data: Optional[Dict] = None) -> None:
    """
    Распространить данные штампа на все блоки страницы.
    Если на странице есть штамп - мержим его с inherited_data.
    Если штампа нет - используем inherited_data.
    """
    blocks = page.get("blocks", [])
    stamp_json = find_page_stamp_dict(page)

    if stamp_json:
        merged = dict(stamp_json)
        if inherited_data:
            for field in INHERITABLE_STAMP_FIELDS:
                if not merged.get(field):
                    if inherited_data.get(field):
                        merged[field] = inherited_data[field]
        for blk in blocks:
            blk["stamp_data"] = merged
    elif inherited_data:
        for blk in blocks:
            blk["stamp_data"] = inherited_data


# =============================================================================
# Функции для дедупликации linked блоков (export_mode="qa")
# =============================================================================


def _extract_clean_text_from_html(ocr_text: str) -> str:
    """Извлечь чистый текст из ocr_text (может быть HTML или plain text)."""
    if not ocr_text:
        return ""

    text = ocr_text.strip()
    if not text:
        return ""

    # Если HTML - удаляем теги
    if text.startswith("<") or "<" in text[:100]:
        # Удаляем HTML теги
        text = re.sub(r"<[^>]+>", " ", text)
        # Декодируем HTML entities
        text = text.replace("&nbsp;", " ")
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")

    # Нормализуем пробелы
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_linked_blocks_index(pages: List) -> Dict[str, Any]:
    """
    Построить индекс linked блоков для дедупликации (для Page объектов).

    Returns:
        Dict с ключами:
        - block_by_id: {block_id -> block}
        - derived_ids: Set[str] - ID TEXT блоков, помеченных как derived
        - linked_ocr_text: {image_block_id -> clean_ocr_text из связанного TEXT блока}
    """
    block_by_id: Dict[str, Any] = {}
    derived_ids: Set[str] = set()
    linked_ocr_text: Dict[str, str] = {}

    # Шаг 1: Построить индекс всех блоков
    for page in pages:
        for block in page.blocks:
            block_by_id[block.id] = block

    # Шаг 2: Обработать linked пары
    processed_pairs: Set[tuple] = set()

    for page in pages:
        for block in page.blocks:
            linked_id = getattr(block, "linked_block_id", None)
            if not linked_id or linked_id not in block_by_id:
                continue

            # Избегаем двойной обработки пары
            pair_key = tuple(sorted([block.id, linked_id]))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            linked_block = block_by_id[linked_id]
            block_type = (
                block.block_type.value
                if hasattr(block.block_type, "value")
                else block.block_type
            )
            linked_type = (
                linked_block.block_type.value
                if hasattr(linked_block.block_type, "value")
                else linked_block.block_type
            )

            # Определяем IMAGE и TEXT блоки в паре
            if block_type == "image" and linked_type == "text":
                image_block, text_block = block, linked_block
            elif block_type == "text" and linked_type == "image":
                image_block, text_block = linked_block, block
            else:
                continue  # Не IMAGE+TEXT пара

            # Помечаем TEXT как derived
            derived_ids.add(text_block.id)

            # Извлекаем clean_ocr_text из TEXT блока
            text_ocr = getattr(text_block, "ocr_text", None)
            if text_ocr:
                clean_text = _extract_clean_text_from_html(text_ocr)
                if clean_text:
                    linked_ocr_text[image_block.id] = clean_text

    logger.debug(
        f"build_linked_blocks_index: {len(derived_ids)} derived, "
        f"{len(linked_ocr_text)} linked_ocr_text"
    )

    return {
        "block_by_id": block_by_id,
        "derived_ids": derived_ids,
        "linked_ocr_text": linked_ocr_text,
    }


def build_linked_blocks_index_dict(pages: List[Dict]) -> Dict[str, Any]:
    """
    Построить индекс linked блоков для дедупликации (для dict структуры).

    Returns:
        Dict с ключами:
        - block_by_id: {block_id -> block dict}
        - derived_ids: Set[str] - ID TEXT блоков, помеченных как derived
        - linked_ocr_text: {image_block_id -> clean_ocr_text из связанного TEXT блока}
    """
    block_by_id: Dict[str, Dict] = {}
    derived_ids: Set[str] = set()
    linked_ocr_text: Dict[str, str] = {}

    # Шаг 1: Построить индекс всех блоков
    for page in pages:
        for block in page.get("blocks", []):
            block_by_id[block["id"]] = block

    # Шаг 2: Обработать linked пары
    processed_pairs: Set[tuple] = set()

    for page in pages:
        for block in page.get("blocks", []):
            linked_id = block.get("linked_block_id")
            if not linked_id or linked_id not in block_by_id:
                continue

            pair_key = tuple(sorted([block["id"], linked_id]))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            linked_block = block_by_id[linked_id]
            block_type = block.get("block_type", "text")
            linked_type = linked_block.get("block_type", "text")

            if block_type == "image" and linked_type == "text":
                image_block, text_block = block, linked_block
            elif block_type == "text" and linked_type == "image":
                image_block, text_block = linked_block, block
            else:
                continue

            derived_ids.add(text_block["id"])

            # Извлекаем текст из TEXT блока (ocr_html или ocr_text)
            text_ocr = text_block.get("ocr_html") or text_block.get("ocr_text", "")
            if text_ocr:
                clean_text = _extract_clean_text_from_html(text_ocr)
                if clean_text:
                    linked_ocr_text[image_block["id"]] = clean_text

    logger.debug(
        f"build_linked_blocks_index_dict: {len(derived_ids)} derived, "
        f"{len(linked_ocr_text)} linked_ocr_text"
    )

    return {
        "block_by_id": block_by_id,
        "derived_ids": derived_ids,
        "linked_ocr_text": linked_ocr_text,
    }
