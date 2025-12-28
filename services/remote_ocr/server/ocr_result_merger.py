"""Объединение OCR результатов: annotation.json + ocr_result.html -> result.json"""
from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

UUID_LIKE_RE = re.compile(
    r"([0-9A-Za-z]{8}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{12})"
)

# Паттерн для маркеров блоков: [[BLOCK ID: uuid]] или похожие варианты OCR
BLOCK_MARKER_RE = re.compile(
    r"\[\[?\s*BLOCK[\s_]*ID\s*[:\-]?\s*"
    r"([0-9A-Za-z]{8}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{12})"
    r"\s*\]?\]?",
    re.IGNORECASE
)

OCR_REPLACEMENTS = {
    "O": "0", "o": "0",
    "I": "1", "l": "1", "|": "1", "!": "1", "і": "1", "І": "1",
    "S": "5", "s": "5",
    "G": "6", "g": "6",
}


def extract_uuid_candidates(text: str) -> list[str]:
    """Извлечь кандидатов UUID из текста."""
    if not text:
        return []
    return UUID_LIKE_RE.findall(text)


def normalize_uuid_text(s: str) -> Optional[str]:
    """
    Нормализация OCR-кандидата UUID в канонический формат.
    Устойчиво к типичным OCR-ошибкам.
    """
    if not s:
        return None
    s = s.strip()

    hex_chars = []
    for ch in s:
        ch = OCR_REPLACEMENTS.get(ch, ch)
        ch_low = ch.lower()
        if ch_low in "0123456789abcdef":
            hex_chars.append(ch_low)

    hex32 = "".join(hex_chars)
    if len(hex32) < 30:
        return None

    if len(hex32) > 32:
        hex32 = hex32[:32]

    if len(hex32) != 32:
        return None

    return f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"


def match_uuid(
    candidate_raw: str,
    expected_ids: list[str],
    expected_set: set[str],
    score_cutoff: int = 92
) -> tuple[Optional[str], float]:
    """Сопоставить кандидата UUID с ожидаемыми ID."""
    norm = normalize_uuid_text(candidate_raw)
    if norm and norm in expected_set:
        return norm, 100.0

    # Простой fuzzy matching без rapidfuzz
    if norm:
        best_match = None
        best_score = 0.0
        for expected in expected_ids:
            # Подсчёт совпадающих символов
            matches = sum(1 for a, b in zip(norm, expected) if a == b)
            score = (matches / max(len(norm), len(expected))) * 100
            if score > best_score and score >= score_cutoff:
                best_match = expected
                best_score = score
        if best_match:
            return best_match, best_score

    return None, 0.0


def build_segments_from_html(
    html_text: str,
    expected_ids: list[str],
    score_cutoff: int = 92
) -> tuple[dict[str, str], dict[str, dict]]:
    """
    Построить сегменты HTML для каждого блока используя regex.
    
    Returns:
        segments: dict[block_id -> html_fragment]
        meta: dict[block_id -> {method, match_score, marker_text_sample}]
    """
    expected_set = set(expected_ids)
    segments: dict[str, str] = {}
    meta: dict[str, dict] = {}

    # Находим все маркеры блоков с их позициями
    markers = []
    for match in BLOCK_MARKER_RE.finditer(html_text):
        uuid_candidate = match.group(1)
        matched_id, score = match_uuid(uuid_candidate, expected_ids, expected_set, score_cutoff)
        if matched_id:
            markers.append({
                "start": match.start(),
                "end": match.end(),
                "block_id": matched_id,
                "score": score,
                "marker_text": match.group(0)[:120]
            })

    if not markers:
        # Фоллбек: ищем блоки по div.block структуре
        block_pattern = re.compile(
            r'<div[^>]*class="[^"]*block[^"]*"[^>]*>(.*?)</div>\s*</div>',
            re.DOTALL | re.IGNORECASE
        )
        for match in block_pattern.finditer(html_text):
            content = match.group(1)
            cands = extract_uuid_candidates(content)
            for cand in cands:
                matched_id, score = match_uuid(cand, expected_ids, expected_set, score_cutoff)
                if matched_id and matched_id not in segments:
                    # Извлекаем block-content
                    content_match = re.search(
                        r'<div[^>]*class="[^"]*block-content[^"]*"[^>]*>(.*?)</div>',
                        content, re.DOTALL | re.IGNORECASE
                    )
                    if content_match:
                        segments[matched_id] = content_match.group(1).strip()
                        meta[matched_id] = {
                            "method": ["fallback"],
                            "match_score": score,
                            "marker_text_sample": cand[:120]
                        }
                    break
        return segments, meta

    # Сортируем маркеры по позиции
    markers.sort(key=lambda x: x["start"])

    # Извлекаем контент между маркерами
    for i, marker in enumerate(markers):
        block_id = marker["block_id"]
        content_start = marker["end"]
        content_end = markers[i + 1]["start"] if i + 1 < len(markers) else len(html_text)
        
        # Извлекаем HTML между маркерами
        fragment = html_text[content_start:content_end].strip()
        
        # Убираем закрывающие теги от маркера и открывающие от следующего
        fragment = re.sub(r'^[\s\S]*?(?=<[a-z])', '', fragment, count=1)
        fragment = re.sub(r'<div[^>]*class="[^"]*block-header[^"]*"[^>]*>[\s\S]*$', '', fragment)
        fragment = fragment.strip()

        if not fragment:
            continue

        if block_id in segments:
            segments[block_id] += "\n" + fragment
            meta[block_id]["match_score"] = max(meta[block_id]["match_score"], marker["score"])
        else:
            segments[block_id] = fragment
            meta[block_id] = {
                "method": ["marker"],
                "match_score": marker["score"],
                "marker_text_sample": marker["marker_text"]
            }

    return segments, meta


def merge_ocr_results(
    annotation_path: Path,
    ocr_html_path: Path,
    output_path: Path,
    score_cutoff: int = 92
) -> bool:
    """
    Объединить annotation.json и ocr_result.html в result.json.
    
    Добавляет к каждому блоку:
    - ocr_html: HTML-фрагмент блока
    - ocr_meta: {method, match_score, marker_text_sample}
    
    Returns:
        True если успешно, False при ошибке
    """
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
            for blk in page.get("blocks", []):
                bid = blk["id"]
                blk["ocr_html"] = segments.get(bid, "")
                blk["ocr_meta"] = meta.get(bid, {"method": [], "match_score": 0.0, "marker_text_sample": ""})
                if blk["ocr_html"]:
                    matched += 1
                else:
                    missing.append(bid)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        if missing:
            logger.warning(f"Не найдено HTML для {len(missing)} блоков. Примеры: {missing[:3]}")
        
        logger.info(f"result.json сохранён: {output_path} ({matched}/{len(expected_ids)} блоков сопоставлено)")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка объединения OCR результатов: {e}", exc_info=True)
        return False

