"""Форматтеры данных в Markdown для OCR результатов."""
import json as json_module
from typing import Dict

from rd_pipeline.common import (
    extract_image_ocr_data,
    is_image_ocr_json,
    sanitize_markdown,
)


def format_stamp_md(stamp_data: Dict) -> str:
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


def format_image_ocr_md(data: dict) -> str:
    """Форматировать данные OCR изображения в компактный Markdown."""
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


def format_generic_json_md(data: dict, max_depth: int = 3) -> str:
    """Универсальный fallback для форматирования любого JSON в Markdown."""
    if max_depth <= 0:
        return ""

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


def process_ocr_content(ocr_text: str) -> str:
    """Обработать содержимое блока и конвертировать в Markdown."""
    if not ocr_text:
        return ""

    text = ocr_text.strip()
    if not text:
        return ""

    # JSON контент
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json_module.loads(text)
            if isinstance(parsed, dict):
                if is_image_ocr_json(parsed):
                    return format_image_ocr_md(parsed)
                # Универсальный fallback для любого JSON
                formatted = format_generic_json_md(parsed)
                if formatted:
                    return formatted
            elif isinstance(parsed, list):
                # Для списков тоже используем fallback
                formatted = format_generic_json_md({"items": parsed})
                if formatted:
                    return formatted
            # Если ничего не извлеклось - возвращаем как есть (но не сырой JSON)
            return ""
        except json_module.JSONDecodeError:
            pass

    # Обычный текст - применяем санитизацию markdown
    return sanitize_markdown(text)
