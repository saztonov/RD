"""Объединение OCR результатов: annotation.json + ocr_result.html -> result.json"""
from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Optional

from .ocr_html_parser import build_segments_from_html

logger = logging.getLogger(__name__)


def _parse_ocr_json(ocr_text: Optional[str]) -> Optional[dict]:
    """Попытаться распарсить ocr_text как JSON."""
    if not ocr_text:
        return None
    
    text = ocr_text.strip()
    if not text:
        return None
    
    # Если начинается с { или [ — пробуем как JSON
    if text.startswith('{') or text.startswith('['):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    
    # Ищем JSON внутри markdown ```json ... ```
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    return None


def _build_crop_url(block_id: str, r2_public_url: str, project_name: str) -> str:
    """Сформировать URL кропа для блока."""
    return f"{r2_public_url}/tree_docs/{project_name}/crops/{block_id}.pdf"


# Поля штампа, наследуемые на страницы без штампа
INHERITABLE_STAMP_FIELDS = ("document_code", "project_name", "stage", "organization")


def _find_page_stamp_json(page: dict) -> Optional[dict]:
    """Найти JSON штампа на странице."""
    for blk in page.get("blocks", []):
        if (blk.get("block_type") == "image" and 
            blk.get("category_code") == "stamp"):
            return blk.get("ocr_json")
    return None


def _collect_inheritable_stamp_data(pages: list) -> Optional[dict]:
    """Собрать общие поля штампа с любой страницы где есть штамп."""
    for page in pages:
        stamp_json = _find_page_stamp_json(page)
        if stamp_json:
            inherited = {}
            for field in INHERITABLE_STAMP_FIELDS:
                if stamp_json.get(field):
                    inherited[field] = stamp_json[field]
            if inherited:
                return inherited
    return None


def _propagate_stamp_data(page: dict, inherited_data: Optional[dict] = None) -> None:
    """
    Распространить данные штампа на все блоки страницы.
    Если на странице есть штамп - используем его ocr_json.
    Если штампа нет - используем inherited_data (общие поля с других страниц).
    """
    blocks = page.get("blocks", [])
    
    # Ищем блок штампа на этой странице
    stamp_json = _find_page_stamp_json(page)
    
    if stamp_json:
        # Копируем stamp_data во все блоки страницы
        for blk in blocks:
            blk["stamp_data"] = stamp_json
    elif inherited_data:
        # Наследуем общие поля с других страниц
        for blk in blocks:
            blk["stamp_data"] = inherited_data


def merge_ocr_results(
    annotation_path: Path,
    ocr_html_path: Path,
    output_path: Path,
    project_name: Optional[str] = None,
    r2_public_url: Optional[str] = None,
    score_cutoff: int = 90
) -> bool:
    """
    Объединить annotation.json и ocr_result.html в result.json.
    
    Добавляет к каждому блоку:
    - ocr_html: HTML-фрагмент блока
    - ocr_json: распарсенный JSON из ocr_text (для IMAGE блоков)
    - crop_url: ссылка на кроп (для IMAGE блоков)
    - ocr_meta: {method, match_score, marker_text_sample}
    
    Returns:
        True если успешно, False при ошибке
    """
    if not r2_public_url:
        r2_public_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
    
    try:
        if not annotation_path.exists():
            logger.warning(f"annotation.json не найден: {annotation_path}")
            return False
        
        if not ocr_html_path.exists():
            logger.warning(f"ocr_result.html не найден: {ocr_html_path}")
            return False
        
        with open(annotation_path, "r", encoding="utf-8") as f:
            ann = json.load(f)
        
        expected_ids = [b["id"] for p in ann.get("pages", []) for b in p.get("blocks", [])]
        
        if not expected_ids:
            logger.info("Нет блоков для обработки")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(ann, f, ensure_ascii=False, indent=2)
            return True
        
        with open(ocr_html_path, "r", encoding="utf-8") as f:
            html_text = f.read()
        
        segments, meta = build_segments_from_html(html_text, expected_ids, score_cutoff=score_cutoff)
        
        result = deepcopy(ann)
        missing = []
        matched = 0
        
        for page in result.get("pages", []):
            # Конвертируем page_number в 1-based для внешнего формата
            if "page_number" in page:
                page["page_number"] = page["page_number"] + 1
            for blk in page.get("blocks", []):
                bid = blk["id"]
                block_type = blk.get("block_type", "text")
                
                # Конвертируем page_index в 1-based для внешнего формата
                if "page_index" in blk:
                    blk["page_index"] = blk["page_index"] + 1
                
                # HTML фрагмент
                blk["ocr_html"] = segments.get(bid, "")
                blk["ocr_meta"] = meta.get(bid, {"method": [], "match_score": 0.0, "marker_text_sample": ""})
                
                # Для IMAGE блоков: парсим JSON из ocr_text и добавляем crop_url
                if block_type == "image":
                    ocr_text = blk.get("ocr_text", "")
                    parsed_json = _parse_ocr_json(ocr_text)
                    if parsed_json:
                        blk["ocr_json"] = parsed_json
                    
                    # Добавляем ссылку на кроп
                    if project_name:
                        blk["crop_url"] = _build_crop_url(bid, r2_public_url, project_name)
                    elif blk.get("image_file"):
                        # Fallback: используем image_file если есть
                        crop_name = Path(blk["image_file"]).name
                        blk["crop_url"] = f"{r2_public_url}/crops/{crop_name}"
                
                if blk["ocr_html"]:
                    matched += 1
                else:
                    missing.append(bid)
        
        # Собираем общие данные штампа для страниц без штампа
        inherited_stamp = _collect_inheritable_stamp_data(result.get("pages", []))
        
        # Распространение данных штампа на все блоки всех страниц
        for page in result.get("pages", []):
            _propagate_stamp_data(page, inherited_stamp)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        if missing:
            logger.warning(f"Не найдено HTML для {len(missing)} блоков. Примеры: {missing[:3]}")
        
        logger.info(f"result.json сохранён: {output_path} ({matched}/{len(expected_ids)} блоков сопоставлено)")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка объединения OCR результатов: {e}", exc_info=True)
        return False
