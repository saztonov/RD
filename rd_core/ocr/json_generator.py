"""Генератор структурированного JSON из OCR результатов"""
import logging
import os
import re
import json as json_module
from pathlib import Path
from typing import List

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

