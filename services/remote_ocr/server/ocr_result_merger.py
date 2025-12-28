"""Объединение OCR результатов: annotation.json + ocr_result.html -> result.json"""
from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

try:
    from rapidfuzz import process, fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

logger = logging.getLogger(__name__)

UUID_LIKE_RE = re.compile(
    r"([0-9A-Za-z]{8}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{12})"
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

    if norm and RAPIDFUZZ_AVAILABLE:
        best = process.extractOne(norm, expected_ids, scorer=fuzz.ratio, score_cutoff=score_cutoff)
        if best:
            return best[0], float(best[1])

    return None, 0.0


def build_segments_with_meta(
    soup: BeautifulSoup,
    expected_ids: list[str],
    score_cutoff: int = 92
) -> tuple[dict[str, str], dict[str, dict]]:
    """
    Построить сегменты HTML для каждого блока.
    
    Returns:
        segments: dict[block_id -> html_fragment]
        meta: dict[block_id -> {method, match_score, marker_text_sample}]
    """
    expected_set = set(expected_ids)
    segments: dict[str, str] = {}
    meta: dict[str, dict] = {}

    containers = soup.select("div.page")
    if not containers:
        containers = [soup.body] if soup.body else [soup]

    # 1) Основной путь: режем по маркерам [[BLOCK ID: ...]]
    for container in containers:
        children = list(container.find_all(recursive=False))
        delims = []

        for idx, child in enumerate(children):
            txt = child.get_text(" ", strip=True)
            if not txt:
                continue

            if ("block" in txt.lower()) or ("id" in txt.lower()) or ("[[" in txt) or ("]]" in txt):
                cands = extract_uuid_candidates(txt)
                if not cands:
                    continue

                matched, score = match_uuid(cands[0], expected_ids, expected_set, score_cutoff=score_cutoff)
                if matched:
                    delims.append((idx, matched, score, txt))

        if not delims:
            continue

        for j, (idx, bid, score, raw_txt) in enumerate(delims):
            start = idx + 1
            end = delims[j + 1][0] if (j + 1) < len(delims) else len(children)
            frag_nodes = children[start:end]
            frag_html = "".join(str(n) for n in frag_nodes).strip()

            if not frag_html:
                continue

            if bid in segments:
                segments[bid] += "\n" + frag_html
                meta[bid]["match_score"] = max(meta[bid]["match_score"], score)
                meta[bid]["method"].add("marker")
            else:
                segments[bid] = frag_html
                meta[bid] = {
                    "method": {"marker"},
                    "match_score": score,
                    "marker_text_sample": raw_txt[:120],
                }

    # 2) Фоллбек: ищем UUID в block-content (для image-блоков с URL на crop)
    for block_div in soup.select("div.block"):
        content_div = block_div.select_one("div.block-content")
        if not content_div:
            continue

        html = str(content_div)
        cands = extract_uuid_candidates(html)
        if not cands:
            continue

        best_id = None
        best_score = 0.0
        best_raw = None

        for cand in cands:
            m, s = match_uuid(cand, expected_ids, expected_set, score_cutoff=score_cutoff)
            if m and s > best_score:
                best_id, best_score, best_raw = m, s, cand

        if not best_id or best_id in segments:
            continue

        frag_html = "".join(str(n) for n in content_div.contents).strip()
        if not frag_html:
            continue

        segments[best_id] = frag_html
        meta[best_id] = {
            "method": {"fallback"},
            "match_score": best_score,
            "marker_text_sample": (best_raw or "")[:120],
        }

    # Приводим method set -> list (для JSON)
    for bid in meta:
        meta[bid]["method"] = sorted(list(meta[bid]["method"]))

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
            # Сохраняем как есть
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(ann, f, ensure_ascii=False, indent=2)
            return True
        
        with open(ocr_html_path, "r", encoding="utf-8") as f:
            html_text = f.read()
        
        try:
            soup = BeautifulSoup(html_text, "lxml")
        except Exception:
            # Fallback парсер
            soup = BeautifulSoup(html_text, "html.parser")
        
        segments, meta = build_segments_with_meta(soup, expected_ids, score_cutoff=score_cutoff)
        
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

