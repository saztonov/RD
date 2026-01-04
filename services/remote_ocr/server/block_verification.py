"""Верификация и повторное распознавание пропущенных блоков"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


def verify_and_retry_missing_blocks(
    result_json_path: Path,
    pdf_path: Path,
    work_dir: Path,
    datalab_backend,
) -> bool:
    """
    Верификация блоков после OCR и повторное распознавание пропущенных.
    
    Args:
        result_json_path: путь к result.json
        pdf_path: путь к PDF файлу
        work_dir: рабочая директория
        datalab_backend: OCR backend для повторного распознавания
        
    Returns:
        True если были найдены и обработаны пропущенные блоки
    """
    if not result_json_path.exists():
        logger.warning(f"result.json не найден: {result_json_path}")
        return False

    with open(result_json_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    # Находим блоки без OCR результата
    missing_blocks = []
    for page in result.get("pages", []):
        for blk in page.get("blocks", []):
            block_type = blk.get("block_type", "text")
            block_id = blk.get("id", "")
            ocr_html = blk.get("ocr_html", "").strip()
            category_code = blk.get("category_code", "")
            
            # Пропускаем штампы и image блоки (они обрабатываются отдельно)
            if category_code == "stamp" or block_type == "image":
                continue
            
            # Проверяем только текстовые и табличные блоки
            if block_type in ["text", "table"] and not ocr_html:
                missing_blocks.append({
                    "block": blk,
                    "page_index": blk.get("page_index", 1) - 1,  # Конвертируем в 0-based
                })

    if not missing_blocks:
        logger.info("✅ Все текстовые блоки распознаны")
        return False

    logger.warning(f"⚠️ Найдено {len(missing_blocks)} нераспознанных текстовых блоков")
    
    # Создаём директорию для кропов
    retry_crops_dir = work_dir / "retry_crops"
    retry_crops_dir.mkdir(exist_ok=True)

    # Обрабатываем каждый блок отдельно
    from .pdf_streaming import StreamingPDFProcessor
    from rd_core.models import Block
    
    successful_retries = 0
    
    with StreamingPDFProcessor(str(pdf_path)) as processor:
        for idx, item in enumerate(missing_blocks):
            blk_data = item["block"]
            block_id = blk_data["id"]
            page_index = item["page_index"]
            
            logger.info(f"[{idx+1}/{len(missing_blocks)}] Повторное распознавание блока {block_id}")
            
            try:
                # Создаём Block объект для crop
                block_obj, _ = Block.from_dict(blk_data, migrate_ids=False)
                
                # Вырезаем кроп
                crop = processor.crop_block_image(block_obj, padding=5)
                if not crop:
                    logger.warning(f"Не удалось создать кроп для блока {block_id}")
                    continue
                
                # Сохраняем кроп для отладки
                crop_path = retry_crops_dir / f"{block_id}.png"
                crop.save(crop_path, "PNG")
                
                # Отправляем на распознавание в datalab
                ocr_text = datalab_backend.recognize(crop)
                crop.close()
                
                if ocr_text and not ocr_text.startswith("[Ошибка"):
                    # Обновляем блок в result.json
                    blk_data["ocr_html"] = ocr_text
                    blk_data["ocr_meta"] = {
                        "method": ["retry_verification"],
                        "match_score": 100.0,
                        "marker_text_sample": "",
                    }
                    successful_retries += 1
                    logger.info(f"✅ Блок {block_id} успешно распознан (длина: {len(ocr_text)})")
                else:
                    logger.warning(f"❌ Блок {block_id} не распознан: {ocr_text[:100] if ocr_text else 'пусто'}")
                    
            except Exception as e:
                logger.error(f"Ошибка обработки блока {block_id}: {e}", exc_info=True)
                continue

    # Сохраняем обновлённый result.json
    if successful_retries > 0:
        with open(result_json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ result.json обновлён ({successful_retries} блоков добавлено)")
        
        # Регенерируем HTML и MD
        _regenerate_output_files(result, work_dir, result_json_path)
        
    logger.info(f"Верификация завершена: {successful_retries}/{len(missing_blocks)} блоков восстановлено")
    return successful_retries > 0


def _regenerate_output_files(result: dict, work_dir: Path, result_json_path: Path):
    """Регенерировать HTML и MD после обновления result.json"""
    from .ocr_result_merger import regenerate_html_from_result, regenerate_md_from_result
    
    try:
        # Регенерируем HTML
        html_path = work_dir / "ocr_result.html"
        doc_name = result.get("pdf_path", "OCR Result")
        regenerate_html_from_result(result, html_path, doc_name=doc_name)
        logger.info(f"✅ HTML регенерирован: {html_path}")
        
        # Регенерируем MD
        md_path = work_dir / "document.md"
        regenerate_md_from_result(result, md_path, doc_name=doc_name)
        logger.info(f"✅ MD регенерирован: {md_path}")
    except Exception as e:
        logger.error(f"Ошибка регенерации файлов: {e}", exc_info=True)
