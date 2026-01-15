"""Функции для работы с данными OCR изображений."""
import re
from typing import Any, Dict


def extract_image_ocr_data(data: dict) -> Dict[str, Any]:
    """
    Извлечь структурированные данные из JSON блока изображения.

    Поддерживает два формата:
    1. Старый формат: content_summary, detailed_description, clean_ocr_text, key_entities
    2. Новый формат: analysis (с raw_text, personnel, axes и др.), raw_pdfplumber_text

    Returns:
        dict с полями: location, zone_name, grid_lines, content_summary,
        detailed_description, clean_ocr_text, key_entities, raw_text, personnel, axes, etc.
    """
    result = {}

    # Извлекаем analysis если есть
    analysis = data.get("analysis", {})
    if isinstance(analysis, dict):
        # Новый формат: raw_text содержит готовый markdown
        if analysis.get("raw_text"):
            result["raw_text"] = analysis["raw_text"]

        # Организация
        if analysis.get("organization"):
            result["organization"] = analysis["organization"]

        # Персонал
        if analysis.get("personnel"):
            result["personnel"] = analysis["personnel"]

        # Информация о листе
        if analysis.get("sheet_info"):
            result["sheet_info"] = analysis["sheet_info"]

        # Детали проекта
        if analysis.get("project_details"):
            result["project_details"] = analysis["project_details"]

        # Оси
        if analysis.get("axes"):
            result["axes"] = analysis["axes"]

        # Разрезы
        if analysis.get("sections"):
            result["sections"] = analysis["sections"]

        # Примечания
        if analysis.get("notes_fragment"):
            result["notes_fragment"] = analysis["notes_fragment"]

    # Сырой текст из pdfplumber (fallback)
    if data.get("raw_pdfplumber_text"):
        result["raw_pdfplumber_text"] = data["raw_pdfplumber_text"]

    # Старый формат: извлекаем данные из корня или analysis
    source = analysis if analysis else data

    # Локация
    location = source.get("location")
    if location:
        if isinstance(location, dict):
            result["zone_name"] = location.get("zone_name", "")
            result["grid_lines"] = location.get("grid_lines", "")
        else:
            result["location_text"] = str(location)

    # Описания (старый формат)
    if source.get("content_summary"):
        result["content_summary"] = source["content_summary"]
    if source.get("detailed_description"):
        result["detailed_description"] = source["detailed_description"]

    # Распознанный текст - нормализуем
    clean_ocr = source.get("clean_ocr_text", "")
    if clean_ocr:
        clean_ocr = re.sub(r"•\s*", "", clean_ocr)
        clean_ocr = re.sub(r"\s+", " ", clean_ocr).strip()
        result["clean_ocr_text"] = clean_ocr

    # Ключевые сущности
    key_entities = source.get("key_entities", [])
    if isinstance(key_entities, list):
        result["key_entities"] = key_entities[:20]  # Максимум 20

    return result


def is_image_ocr_json(data: dict) -> bool:
    """Проверить, является ли JSON данными OCR изображения."""
    if not isinstance(data, dict):
        return False

    # Старые поля (для совместимости)
    old_fields = ["content_summary", "detailed_description", "clean_ocr_text"]

    # Новые поля из нового формата OCR
    new_fields = ["analysis", "raw_pdfplumber_text", "doc_metadata"]

    # Проверяем старый формат
    if any(key in data or (data.get("analysis") and key in data["analysis"]) for key in old_fields):
        return True

    # Проверяем новый формат
    if any(key in data for key in new_fields):
        return True

    return False
