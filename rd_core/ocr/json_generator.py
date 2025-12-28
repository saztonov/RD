"""Генератор структурированного JSON из OCR результатов"""
import copy
import difflib
import logging
import os
import re
import json as json_module
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Регулярки для извлечения UUID
UUID_RE = re.compile(r"[0-9a-fA-F]{8}[-_][0-9a-fA-F]{4}[-_][0-9a-fA-F]{4}[-_][0-9a-fA-F]{4}[-_][0-9a-fA-F]{12}")
# Поддержка и [[...]] и [[[...]]] (с тройными скобками)
BRACKET_RE = re.compile(r"\[\[\[?\s*(.*?)\s*\]?\]\]")  # содержимое внутри [[ ... ]] или [[[ ... ]]]


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
    """
    Извлечь HTML из ocr_result, избегая дублирования.
    
    Структура ocr_result:
    - children[0].html содержит объединённый HTML всех дочерних элементов
    - children[0].children[*].html содержит те же данные по отдельности
    
    Берём только html верхнего уровня из каждого children, 
    НЕ спускаясь в вложенные children.
    """
    html_parts = []
    
    if isinstance(ocr_result, dict):
        # Если есть html на этом уровне - берём его
        if "html" in ocr_result and isinstance(ocr_result["html"], str):
            html_parts.append(ocr_result["html"])
            # НЕ спускаемся в children, т.к. html уже содержит их контент
        elif "children" in ocr_result and isinstance(ocr_result["children"], list):
            # Если нет html, но есть children - обрабатываем их
            for child in ocr_result["children"]:
                html_parts.append(_extract_all_html_from_ocr_result(child))
    elif isinstance(ocr_result, list):
        for item in ocr_result:
            html_parts.append(_extract_all_html_from_ocr_result(item))
    
    return "".join(html_parts)


# ========== Новый алгоритм группировки HTML по BLOCK_ID ==========

def _canonicalize_uuid(text: str) -> Optional[str]:
    """
    Пытается вытащить UUID из строки (внутри [[...]]), нормализовать и вернуть.
    """
    if not text:
        return None
    s = text.strip().lower().replace("_", "-")

    # 1) UUID с дефисами/подчёркиваниями
    m = UUID_RE.search(s)
    if m:
        return m.group(0).replace("_", "-").lower()

    # 2) UUID без дефисов: 32 hex -> вставляем дефисы
    hex_only = re.sub(r"[^0-9a-f]", "", s)
    if len(hex_only) >= 32:
        h = hex_only[:32]
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

    return None


def _similarity(a: str, b: str) -> float:
    """Вычисляет схожесть двух строк через SequenceMatcher."""
    return difflib.SequenceMatcher(a=a, b=b).ratio()


def _build_prefix_index(expected_ids: List[str]) -> Dict[str, List[str]]:
    """
    У UUID первая группа (8 символов) обычно распознаётся лучше остальных.
    Это сильно ускоряет нечёткий поиск: сначала ограничиваем пул кандидатов по префиксу.
    """
    idx: Dict[str, List[str]] = {}
    for eid in expected_ids:
        prefix = eid.split("-")[0] if "-" in eid else eid[:8]
        idx.setdefault(prefix, []).append(eid)
    return idx


def _best_fuzzy_match(
    candidate_uuid: str, 
    expected_ids: List[str], 
    prefix_index: Dict[str, List[str]], 
    threshold: float
) -> Optional[Dict]:
    """
    Нечёткое сравнение UUID с использованием SequenceMatcher.
    Возвращает dict с match_id, score и возможно ambiguous_with.
    """
    if not candidate_uuid:
        return None

    cand = candidate_uuid.lower()
    pool = expected_ids

    # Оптимизация: сначала ищем по префиксу
    pref = cand.split("-")[0] if "-" in cand else cand[:8]
    if pref in prefix_index:
        pool = prefix_index[pref]

    best = None
    second = None

    for eid in pool:
        sc = _similarity(cand, eid.lower())
        if best is None or sc > best[1]:
            second = best
            best = (eid, sc)
        elif second is None or sc > second[1]:
            second = (eid, sc)

    if best and best[1] >= threshold:
        out = {"match_id": best[0], "score": best[1]}
        if second and second[1] >= threshold and (best[1] - second[1]) < 0.03:
            out["ambiguous_with"] = second[0]
            out["second_score"] = second[1]
        return out

    return None


def _extract_markers(html: str) -> List[Dict]:
    """
    Находит все [[...]] и возвращает список меток с позициями.
    Важно: режем по границам <p>...</p>, чтобы не оставлять "висящие" <p>.
    """
    markers = []
    for m in BRACKET_RE.finditer(html):
        inside = m.group(1)
        cand_uuid = _canonicalize_uuid(inside)

        # границы абзаца с меткой
        para_start = html.rfind("<p", 0, m.start())
        if para_start == -1 or html.find(">", para_start, m.start()) == -1:
            para_start = m.start()

        para_end = html.find("</p>", m.end())
        para_end = (para_end + len("</p>")) if para_end != -1 else m.end()

        markers.append({
            "raw_token": m.group(0),
            "inside": inside,
            "uuid_cand": cand_uuid,
            "para_start": para_start,
            "para_end": para_end,
        })

    markers.sort(key=lambda x: x["para_start"])
    return markers


def _split_html_by_markers(html: str) -> List[Dict]:
    """
    Возвращает список сегментов:
      [{ marker: {...}, segment_html: "<h1>...</h1>..." }, ...]
    """
    markers = _extract_markers(html)
    if not markers:
        return []

    segments = []
    for i, mk in enumerate(markers):
        start = mk["para_end"]
        end = markers[i + 1]["para_start"] if i + 1 < len(markers) else len(html)
        segments.append({"marker": mk, "segment_html": html[start:end].strip()})

    return segments


def generate_grouped_result_json(
    ocr_json_path: str,
    annotation_json_path: str,
    output_path: str,
    threshold: float = 0.85
) -> str:
    """
    Генерация result.json с группированными HTML блоками.
    
    Алгоритм:
    1. Загружаем разметку из annotation.json и собираем список ожидаемых block_id
    2. Загружаем OCR-результат из preliminary.json (ocr_json_path)
    3. Для каждого OCR-блока типа text извлекаем HTML из children[0].html
    4. Находим разделители [[BLOCK ID: ...]] и режем HTML на сегменты
    5. Нечётко сопоставляем распознанные ID с ожидаемыми block_id
    6. Формируем result.json с ocr_html и ocr_meta для каждого блока
    
    Args:
        ocr_json_path: путь к preliminary JSON с OCR результатами
        annotation_json_path: путь к annotation.json
        output_path: путь для сохранения result.json
        threshold: порог нечёткого совпадения UUID (0.85 = 85%)
    
    Returns:
        Путь к сохранённому файлу
    """
    try:
        # Читаем OCR результаты (preliminary.json)
        with open(ocr_json_path, "r", encoding="utf-8") as f:
            preliminary = json_module.load(f)
        
        # Читаем annotation.json
        with open(annotation_json_path, "r", encoding="utf-8") as f:
            annotation = json_module.load(f)
        
        result = copy.deepcopy(annotation)
        
        # Собираем ожидаемые текстовые block_id из annotation
        expected_text_ids: List[str] = []
        for page in result.get("pages", []):
            for blk in page.get("blocks", []):
                if blk.get("block_type") == "text":
                    expected_text_ids.append(blk["id"])
        
        prefix_index = _build_prefix_index(expected_text_ids)
        
        logger.info(f"generate_grouped_result_json: известно {len(expected_text_ids)} текстовых блоков из annotation")
        
        # Карта: block_id -> {ocr_html, ocr_meta}
        ocr_map: Dict[str, Dict] = {}
        
        for pre_blk in preliminary.get("blocks", []):
            if pre_blk.get("block_type") != "text":
                continue
            
            ocr_result = pre_blk.get("ocr_result") or {}
            children = ocr_result.get("children") or []
            if not children:
                continue
            
            html_full = children[0].get("html") or ""
            if not html_full:
                continue
            
            segments = _split_html_by_markers(html_full)
            
            for seg in segments:
                cand = seg["marker"]["uuid_cand"]
                m = _best_fuzzy_match(cand, expected_text_ids, prefix_index, threshold=threshold) if cand else None
                if not m:
                    continue
                
                block_id = m["match_id"]
                # Если один block_id встретился дважды — оставляем вариант с лучшим score
                prev = ocr_map.get(block_id)
                if prev is None or m["score"] > prev["ocr_meta"]["match_score"]:
                    ocr_map[block_id] = {
                        "ocr_html": seg["segment_html"],
                        "ocr_meta": {
                            "source_pre_block_id": pre_blk.get("block_id"),
                            "marker_raw": seg["marker"]["raw_token"],
                            "marker_inside": seg["marker"]["inside"],
                            "marker_uuid_cand": cand,
                            "match_score": m["score"],
                            "ambiguous_with": m.get("ambiguous_with"),
                            "second_score": m.get("second_score"),
                        }
                    }
        
        logger.info(f"generate_grouped_result_json: найдено {len(ocr_map)} текстовых блоков с HTML")
        
        # Карта image analysis по block_id
        image_analysis_map: Dict[str, Any] = {}
        image_data_map: Dict[str, Dict] = {}
        for pre_blk in preliminary.get("blocks", []):
            if pre_blk.get("block_type") == "image":
                bid = pre_blk.get("block_id")
                image_analysis_map[bid] = pre_blk.get("ocr_result")
                image_data_map[bid] = {
                    "image": pre_blk.get("image"),
                    "operator_hint": pre_blk.get("operator_hint"),
                    "raw_pdfplumber_text": pre_blk.get("raw_pdfplumber_text"),
                }
        
        # Обновляем блоки в result
        missing = []
        for page in result.get("pages", []):
            for blk in page.get("blocks", []):
                bid = blk.get("id")
                block_type = blk.get("block_type")
                
                if block_type == "text":
                    found = ocr_map.get(bid)
                    if found:
                        blk["ocr_html"] = found["ocr_html"]
                        blk["ocr_meta"] = found["ocr_meta"]
                    else:
                        blk["ocr_html"] = None
                        blk["ocr_meta"] = {"status": "not_found"}
                        missing.append(bid)
                
                elif block_type == "image":
                    blk["image_analysis"] = image_analysis_map.get(bid)
                    # Копируем дополнительные данные изображения
                    img_data = image_data_map.get(bid, {})
                    if img_data.get("image"):
                        blk["image"] = img_data["image"]
                    if img_data.get("operator_hint"):
                        blk["operator_hint"] = img_data["operator_hint"]
                    if img_data.get("raw_pdfplumber_text"):
                        blk["raw_pdfplumber_text"] = img_data["raw_pdfplumber_text"]
        
        result["_merge_info"] = {
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "threshold": threshold,
            "missing_text_block_ids": missing,
        }
        
        if missing:
            logger.warning(f"generate_grouped_result_json: не найдено HTML для {len(missing)} блоков: {missing[:5]}...")
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json_module.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Grouped result JSON сохранён: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка генерации grouped result JSON: {e}", exc_info=True)
        raise
