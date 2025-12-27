"""Генератор структурированного JSON из OCR результатов"""
import logging
import os
import re
import json as json_module
from pathlib import Path
from typing import List, Dict, Any, Set

logger = logging.getLogger(__name__)


def extract_block_ids_from_annotation(annotation_path: str) -> Set[str]:
    """Извлекает id блоков из annotation.json или blocks.json"""
    try:
        with open(annotation_path, 'r', encoding='utf-8') as f:
            data = json_module.load(f)
        
        block_ids = set()
        
        # Формат 1: Document формат с pages.blocks
        if "pages" in data:
            for page in data.get("pages", []):
                for block in page.get("blocks", []):
                    if block.get("id"):
                        block_ids.add(block["id"])
        
        # Формат 2: Плоский массив блоков
        elif isinstance(data, list):
            for block in data:
                if isinstance(block, dict) and block.get("id"):
                    block_ids.add(block["id"])
        
        return block_ids
    except Exception as e:
        logger.error(f"Ошибка чтения annotation.json: {e}")
        return set()


def split_children_by_block_id(
    children: List[Dict[str, Any]], 
    annotation_block_ids: Set[str]
) -> List[Dict[str, Any]]:
    """
    Разделяет children по паттернам [[BLOCK_ID: uuid]].
    Элементы между маркерами группируются в один блок.
    """
    block_id_pattern = re.compile(r'\[\[BLOCK_ID:\s*([a-f0-9-]+)\]\]', re.IGNORECASE)
    
    result_blocks = []
    current_block_id = None
    current_elements = []
    
    def flush_current_block():
        nonlocal current_elements, current_block_id
        if current_elements and current_block_id:
            # Собираем HTML всех элементов
            combined_html = ""
            for elem in current_elements:
                html = elem.get("html", "")
                # Удаляем маркеры BLOCK_ID из HTML
                html = block_id_pattern.sub("", html)
                # Убираем пустые <p></p> от маркеров
                html = re.sub(r'<p>\s*</p>', '', html)
                combined_html += html
            
            if combined_html.strip():
                result_blocks.append({
                    "id": current_block_id,
                    "block_type": "UserBlock",
                    "html": combined_html.strip()
                })
        current_elements = []
        current_block_id = None
    
    for child in children:
        # Обрабатываем Page элемент рекурсивно
        if child.get("block_type") == "Page":
            page_children = child.get("children", [])
            if page_children:
                nested_result = split_children_by_block_id(page_children, annotation_block_ids)
                if nested_result:
                    result_blocks.extend(nested_result)
            continue
        
        html = child.get("html", "")
        match = block_id_pattern.search(html)
        
        if match:
            found_id = match.group(1)
            if found_id in annotation_block_ids:
                # Нашли новый маркированный блок - сохраняем предыдущий
                flush_current_block()
                current_block_id = found_id
                current_elements.append(child)
            else:
                # ID не в annotation - просто добавляем к текущему
                if current_block_id:
                    current_elements.append(child)
        else:
            # Нет маркера - добавляем к текущему блоку
            if current_block_id:
                current_elements.append(child)
    
    # Сохраняем последний блок
    flush_current_block()
    
    return result_blocks


def postprocess_ocr_result(ocr_result: Dict[str, Any], annotation_block_ids: Set[str]) -> Dict[str, Any]:
    """
    Постобработка ocr_result: группировка children по BLOCK_ID.
    Оставляет только block_type и html.
    """
    if not ocr_result or not isinstance(ocr_result, dict):
        return ocr_result
    
    children = ocr_result.get("children", [])
    if not children:
        return ocr_result
    
    new_children = split_children_by_block_id(children, annotation_block_ids)
    
    if new_children:
        return {"children": new_children}
    
    return ocr_result


def generate_structured_json(
    pages: List, 
    output_path: str, 
    project_name: str = None, 
    doc_name: str = None,
    annotation_path: str = None
) -> str:
    """
    Генерация JSON документа из размеченных блоков с учетом типов
    
    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения JSON файла
        project_name: имя проекта для формирования ссылки на R2
        doc_name: имя документа PDF
        annotation_path: путь к annotation.json для группировки по BLOCK_ID
    
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
        
        # Загружаем ID блоков из annotation.json если указан
        annotation_block_ids = set()
        if annotation_path:
            annotation_block_ids = extract_block_ids_from_annotation(annotation_path)
            logger.info(f"Загружено {len(annotation_block_ids)} block_id из annotation.json")
        
        all_blocks = []
        for page in pages:
            for block in page.blocks:
                all_blocks.append((page.page_number, block))
        
        logger.info(f"generate_structured_json: всего блоков: {len(all_blocks)}")
        
        all_blocks.sort(key=lambda x: (x[0], x[1].coords_px[1]))
        
        result_blocks = []
        skipped_no_ocr = 0
        
        for page_num, block in all_blocks:
            if not block.ocr_text:
                skipped_no_ocr += 1
                logger.debug(f"Блок {block.id} пропущен: ocr_text={block.ocr_text!r}")
                continue
            
            text = block.ocr_text.strip()
            if not text:
                continue
            
            block_data = {
                "block_id": block.id,
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
                    # Постобработка: группировка по BLOCK_ID если есть annotation
                    if annotation_block_ids and isinstance(parsed, dict):
                        parsed = postprocess_ocr_result(parsed, annotation_block_ids)
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


# Alias для обратной совместимости
generate_structured_markdown = generate_structured_json
