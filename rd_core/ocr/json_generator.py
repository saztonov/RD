"""Генератор структурированного JSON из OCR результатов"""
import logging
import os
import re
import json as json_module
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def generate_structured_json(
    pages: List, 
    output_path: str, 
    project_name: str = None, 
    doc_name: str = None
) -> str:
    """
    Генерация JSON документа из размеченных блоков с учетом типов
    
    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения JSON файла
        project_name: имя проекта для формирования ссылки на R2
        doc_name: имя документа PDF
    
    Returns:
        Путь к сохраненному файлу
    """
    try:
        from rd_core.models import BlockType
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        r2_public_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
        
        if not project_name:
            project_name = output_file.parent.name
        
        all_blocks = []
        for page in pages:
            for idx, block in enumerate(page.blocks):
                # Сохраняем индекс блока для сортировки по номерам (1,2,3...)
                all_blocks.append((page.page_number, idx, block))
        
        logger.info(f"generate_structured_json: всего блоков: {len(all_blocks)}")
        
        # Сортировка по странице и индексу блока (номеру в правом верхнем углу)
        all_blocks.sort(key=lambda x: (x[0], x[1]))
        
        result_blocks = []
        skipped_no_ocr = 0
        
        for page_num, block_idx, block in all_blocks:
            if not block.ocr_text:
                skipped_no_ocr += 1
                logger.debug(f"Блок {block.id} пропущен: ocr_text={block.ocr_text!r}")
                continue
            
            text = block.ocr_text.strip()
            if not text:
                continue
            
            block_data = {
                "block_id": block.id,
                "block_number": block_idx + 1,  # Номер блока (отображается в правом верхнем углу)
                "block_type": block.block_type.value,
                "page": page_num + 1 if page_num is not None else None,
                "coords_px": list(block.coords_px),
                "coords_norm": list(block.coords_norm),
            }
            
            if block.block_type == BlockType.IMAGE:
                image_uri = ""
                mime_type = "image/png"
                if block.image_file:
                    crop_filename = Path(block.image_file).name
                    image_uri = f"{r2_public_url}/tree_docs/{project_name}/crops/{crop_filename}"
                    ext = Path(block.image_file).suffix.lower()
                    if ext == ".pdf":
                        mime_type = "application/pdf"
                    elif ext in (".jpg", ".jpeg"):
                        mime_type = "image/jpeg"
                
                block_data["image"] = {
                    "uri": image_uri,
                    "mime_type": mime_type
                }
                block_data["operator_hint"] = block.hint or ""
                block_data["raw_pdfplumber_text"] = block.pdfplumber_text or ""
                
                # Парсим OCR результат как JSON если возможно
                try:
                    json_match = re.search(r'\{[\s\S]*\}', text)
                    if json_match:
                        block_data["ocr_result"] = json_module.loads(json_match.group(0))
                    else:
                        block_data["ocr_result"] = {"raw_text": text}
                except json_module.JSONDecodeError:
                    block_data["ocr_result"] = {"raw_text": text}
            
            elif block.block_type == BlockType.TEXT:
                # Парсим OCR результат как JSON если возможно
                try:
                    parsed = json_module.loads(text)
                    block_data["ocr_result"] = parsed
                except json_module.JSONDecodeError:
                    block_data["ocr_result"] = {"raw_text": text}
            
            result_blocks.append(block_data)
        
        logger.info(f"generate_structured_json: обработано {len(result_blocks)} блоков, пропущено без OCR: {skipped_no_ocr}")
        
        result = {
            "doc_name": doc_name or "",
            "project_name": project_name,
            "blocks": result_blocks
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json_module.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Структурированный JSON документ сохранен: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка генерации структурированного JSON: {e}", exc_info=True)
        raise


def _extract_all_html_from_ocr_result(ocr_result: Any) -> str:
    """Рекурсивно извлечь все html поля из ocr_result"""
    html_parts = []
    
    if isinstance(ocr_result, dict):
        if "html" in ocr_result and isinstance(ocr_result["html"], str):
            html_parts.append(ocr_result["html"])
        for key, value in ocr_result.items():
            if key != "html":
                html_parts.append(_extract_all_html_from_ocr_result(value))
    elif isinstance(ocr_result, list):
        for item in ocr_result:
            html_parts.append(_extract_all_html_from_ocr_result(item))
    
    return "".join(html_parts)


def _parse_html_by_block_ids(ocr_json_data: Dict) -> Dict[str, str]:
    """
    Парсит итоговый JSON и группирует HTML по BLOCK_ID.
    
    Находит паттерны [[BLOCK_ID: uuid]] в HTML и группирует контент
    от одного паттерна до следующего.
    
    Returns:
        Dict[block_id, html_content]
    """
    block_html_map: Dict[str, str] = {}
    block_id_pattern = re.compile(r'\[\[BLOCK_ID:\s*([a-f0-9\-]+)\]\]', re.IGNORECASE)
    
    blocks = ocr_json_data.get("blocks", [])
    
    for block in blocks:
        ocr_result = block.get("ocr_result")
        if not ocr_result:
            continue
        
        # Извлекаем все HTML из ocr_result
        full_html = _extract_all_html_from_ocr_result(ocr_result)
        if not full_html:
            continue
        
        # Находим все BLOCK_ID паттерны с их позициями
        matches = list(block_id_pattern.finditer(full_html))
        
        if not matches:
            # Нет паттернов - весь HTML привязываем к block_id из блока
            block_id = block.get("block_id")
            if block_id:
                block_html_map[block_id] = full_html
            continue
        
        # Группируем HTML по паттернам
        for i, match in enumerate(matches):
            block_id = match.group(1)
            start_pos = match.start()
            
            # Конец = начало следующего паттерна или конец строки
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(full_html)
            
            # Извлекаем HTML сегмент (без самого паттерна)
            segment = full_html[match.end():end_pos].strip()
            
            # Убираем обёртку <p>[[BLOCK_ID:...]]</p> если есть
            segment = re.sub(r'^</p>\s*', '', segment)
            segment = re.sub(r'\s*<p>\s*$', '', segment)
            
            if block_id in block_html_map:
                block_html_map[block_id] += "\n" + segment
            else:
                block_html_map[block_id] = segment
    
    return block_html_map


def generate_grouped_result_json(
    ocr_json_path: str,
    annotation_json_path: str,
    output_path: str
) -> str:
    """
    Генерация result.json с группированными HTML блоками.
    
    Берёт блоки из annotation.json и добавляет поле html,
    сгруппированное из итогового OCR JSON по паттернам [[BLOCK_ID: uuid]].
    
    Args:
        ocr_json_path: путь к итоговому JSON с OCR результатами
        annotation_json_path: путь к annotation.json
        output_path: путь для сохранения result.json
    
    Returns:
        Путь к сохранённому файлу
    """
    try:
        # Читаем итоговый OCR JSON
        with open(ocr_json_path, "r", encoding="utf-8") as f:
            ocr_data = json_module.load(f)
        
        # Читаем annotation.json
        with open(annotation_json_path, "r", encoding="utf-8") as f:
            annotation_data = json_module.load(f)
        
        # Парсим HTML по BLOCK_ID
        block_html_map = _parse_html_by_block_ids(ocr_data)
        logger.info(f"generate_grouped_result_json: найдено {len(block_html_map)} блоков с HTML")
        
        # Формируем результат на основе annotation
        result_blocks = []
        
        for page in annotation_data.get("pages", []):
            for block in page.get("blocks", []):
                block_id = block.get("id")
                
                result_block = {
                    "id": block_id,
                    "page_index": block.get("page_index"),
                    "coords_px": block.get("coords_px"),
                    "coords_norm": block.get("coords_norm"),
                    "block_type": block.get("block_type"),
                    "source": block.get("source"),
                    "shape_type": block.get("shape_type"),
                    "html": block_html_map.get(block_id, "")
                }
                
                # Копируем опциональные поля
                if block.get("polygon_points"):
                    result_block["polygon_points"] = block["polygon_points"]
                if block.get("prompt"):
                    result_block["prompt"] = block["prompt"]
                if block.get("hint"):
                    result_block["hint"] = block["hint"]
                
                result_blocks.append(result_block)
        
        result = {
            "pdf_path": annotation_data.get("pdf_path", ""),
            "blocks": result_blocks
        }
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json_module.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Grouped result JSON сохранён: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка генерации grouped result JSON: {e}", exc_info=True)
        raise

