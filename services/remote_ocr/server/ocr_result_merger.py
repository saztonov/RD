"""Объединение OCR результатов: annotation.json + ocr_result.html -> result.json"""
from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Новый формат: BLOCK: XXXX-XXXX-XXX (armor код)
ARMOR_BLOCK_MARKER_RE = re.compile(
    r"BLOCK:\s*([A-Z0-9]{4}[-\s]*[A-Z0-9]{4}[-\s]*[A-Z0-9]{3})",
    re.IGNORECASE
)

# Legacy: UUID формат
UUID_LIKE_RE = re.compile(
    r"([0-9A-Za-z]{8}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{4}[-\s_]*[0-9A-Za-z]{12})"
)

# Legacy паттерн для маркеров блоков: [[BLOCK ID: uuid]]
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


def _levenshtein_ratio(s1: str, s2: str) -> float:
    """
    Вычислить схожесть двух строк (0-100%) на основе расстояния Левенштейна.
    Устойчиво к вставкам/удалениям символов (OCR-ошибки).
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 100.0
    
    len1, len2 = len(s1), len(s2)
    
    # Матрица расстояний (оптимизация памяти - только 2 строки)
    prev = list(range(len2 + 1))
    curr = [0] * (len2 + 1)
    
    for i in range(1, len1 + 1):
        curr[0] = i
        for j in range(1, len2 + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            curr[j] = min(
                prev[j] + 1,      # удаление
                curr[j-1] + 1,    # вставка
                prev[j-1] + cost  # замена
            )
        prev, curr = curr, prev
    
    distance = prev[len2]
    max_len = max(len1, len2)
    return ((max_len - distance) / max_len) * 100


def match_armor_code(
    armor_code: str,
    expected_ids: list[str],
    expected_set: set[str],
) -> tuple[Optional[str], float]:
    """
    Сопоставить armor код (XXXX-XXXX-XXX) с ожидаемыми UUID.
    Использует ArmorID для восстановления и декодирования.
    """
    from .armor_id import match_armor_to_uuid
    
    matched_uuid, score = match_armor_to_uuid(armor_code, expected_ids)
    return matched_uuid, score


def match_uuid(
    candidate_raw: str,
    expected_ids: list[str],
    expected_set: set[str],
    score_cutoff: int = 90
) -> tuple[Optional[str], float]:
    """
    Сопоставить кандидата UUID с ожидаемыми ID (legacy).
    Использует нечёткий поиск с порогом 90%.
    """
    norm = normalize_uuid_text(candidate_raw)
    if norm and norm in expected_set:
        return norm, 100.0

    # Fuzzy matching с учётом вставок/удалений (Левенштейн)
    if norm:
        best_match = None
        best_score = 0.0
        for expected in expected_ids:
            score = _levenshtein_ratio(norm, expected)
            if score > best_score and score >= score_cutoff:
                best_match = expected
                best_score = score
        if best_match:
            return best_match, best_score
    
    # Фоллбек: пробуем без нормализации (для случаев когда OCR сильно исказил)
    if candidate_raw:
        clean = re.sub(r'[^a-f0-9\-]', '', candidate_raw.lower())
        if len(clean) >= 30:
            best_match = None
            best_score = 0.0
            for expected in expected_ids:
                score = _levenshtein_ratio(clean, expected)
                if score > best_score and score >= score_cutoff:
                    best_match = expected
                    best_score = score
            if best_match:
                return best_match, best_score

    return None, 0.0


def _extract_blocks_by_div_structure(
    html_text: str,
    expected_ids: list[str],
    expected_set: set[str],
    segments: dict[str, str],
    meta: dict[str, dict],
    score_cutoff: int = 90
) -> None:
    """
    Фоллбек: извлекает блоки по div.block структуре HTML.
    Полезно для image блоков, где маркер [[BLOCK ID:...]] отсутствует.
    """
    # Паттерн для извлечения блоков: ищем div.block-content и следующий </div></div>
    block_pattern = re.compile(
        r'<div[^>]*class="[^"]*block\s+block-type-(\w+)[^"]*"[^>]*>\s*'
        r'<div[^>]*class="[^"]*block-header[^"]*"[^>]*>([^<]*)</div>\s*'
        r'<div[^>]*class="[^"]*block-content[^"]*"[^>]*>([\s\S]*?)</div></div>',
        re.IGNORECASE
    )
    
    found_count = 0
    for match in block_pattern.finditer(html_text):
        block_type = match.group(1)
        header = match.group(2)
        content = match.group(3).strip()
        
        # Извлекаем UUID из контента (маркер или URL)
        matched_id = None
        match_score = 0.0
        marker_sample = ""
        
        # Сначала ищем новый маркер BLOCK: XXXX-XXXX-XXX
        armor_match = ARMOR_BLOCK_MARKER_RE.search(content)
        if armor_match:
            armor_code = armor_match.group(1)
            matched_id, match_score = match_armor_code(armor_code, expected_ids, expected_set)
            marker_sample = armor_match.group(0)[:60]
        
        # Fallback: legacy маркер [[BLOCK ID:...]]
        if not matched_id:
            marker_match = BLOCK_MARKER_RE.search(content)
            if marker_match:
                cand = marker_match.group(1)
                matched_id, match_score = match_uuid(cand, expected_ids, expected_set, score_cutoff)
                marker_sample = marker_match.group(0)[:60]
        
        # Если маркер не найден, ищем UUID в URL (для image блоков)
        if not matched_id:
            url_pattern = re.compile(r'crops/([a-f0-9\-]{36})\.pdf', re.IGNORECASE)
            url_match = url_pattern.search(content)
            if url_match:
                cand = url_match.group(1)
                # Прямое сравнение - ID из URL точные
                if cand in expected_set:
                    matched_id = cand
                    match_score = 100.0
                    marker_sample = f"URL: {cand}"
        
        if matched_id and matched_id not in segments:
            # Убираем маркеры из контента
            clean_content = ARMOR_BLOCK_MARKER_RE.sub('', content)
            clean_content = BLOCK_MARKER_RE.sub('', clean_content).strip()
            # Убираем обёртку <p>...</p> вокруг маркера
            clean_content = re.sub(r'<p>\s*</p>', '', clean_content).strip()
            
            segments[matched_id] = clean_content
            meta[matched_id] = {
                "method": ["div_structure"],
                "match_score": match_score,
                "marker_text_sample": marker_sample
            }
            found_count += 1
    
    logger.debug(f"_extract_blocks_by_div_structure: found {found_count} blocks by div structure")


def build_segments_from_html(
    html_text: str,
    expected_ids: list[str],
    score_cutoff: int = 90
) -> tuple[dict[str, str], dict[str, dict]]:
    """
    Построить сегменты HTML для каждого блока используя regex.
    
    Логика: ищем маркеры BLOCK: XXXX-XXXX-XXX (новый формат) или [[BLOCK ID: uuid]] (legacy)
    и извлекаем контент ПОСЛЕ каждого маркера до следующего маркера.
    
    Returns:
        segments: dict[block_id -> html_fragment]
        meta: dict[block_id -> {method, match_score, marker_text_sample}]
    """
    expected_set = set(expected_ids)
    segments: dict[str, str] = {}
    meta: dict[str, dict] = {}

    # Находим все маркеры блоков с их позициями
    markers = []
    
    # Новый формат: BLOCK: XXXX-XXXX-XXX
    for match in ARMOR_BLOCK_MARKER_RE.finditer(html_text):
        armor_code = match.group(1)
        matched_id, score = match_armor_code(armor_code, expected_ids, expected_set)
        if matched_id:
            markers.append({
                "start": match.start(),
                "end": match.end(),
                "block_id": matched_id,
                "score": score,
                "marker_text": match.group(0)[:60]
            })
    
    # Legacy формат: [[BLOCK ID: uuid]]
    if not markers:
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
        _extract_blocks_by_div_structure(html_text, expected_ids, expected_set, segments, meta, score_cutoff)
        return segments, meta

    # Сортируем маркеры по позиции
    markers.sort(key=lambda x: x["start"])

    # Извлекаем контент между маркерами
    for i, marker in enumerate(markers):
        block_id = marker["block_id"]
        content_start = marker["end"]
        content_end = markers[i + 1]["start"] if i + 1 < len(markers) else len(html_text)
        
        # Извлекаем HTML между текущим и следующим маркером
        fragment = html_text[content_start:content_end]
        
        # Убираем закрывающий тег </p> или </div> сразу после маркера (обёртка маркера)
        # Формат: BLOCK: XXXX-XXXX-XXX</p>\n... 
        fragment = re.sub(r'^\s*\]?\]?\s*</\w+>\s*', '', fragment)
        # Новый формат: убираем пробелы после BLOCK: code
        fragment = re.sub(r'^\s+', '', fragment)
        # Убираем маркер <p>BLOCK: ...</p> для следующего блока в конце фрагмента
        fragment = re.sub(r'\s*<p>\s*BLOCK:\s*[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{3}\s*</p>\s*$', '', fragment, flags=re.IGNORECASE)
        
        # Убираем открывающий тег <p> или подобный перед следующим маркером
        # Ищем конец полезного контента - до div.block-header или до открывающего <p>[[BLOCK
        fragment = re.sub(r'<div[^>]*class="[^"]*block-header[^"]*"[^>]*>[\s\S]*$', '', fragment)
        fragment = re.sub(r'</div>\s*</div>\s*<div[^>]*class="[^"]*block[\s\S]*$', '', fragment)
        
        # Убираем <p> перед следующим маркером (может содержать только пробелы)
        fragment = re.sub(r'\s*<p>\s*$', '', fragment)
        
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

    # Фоллбек для блоков, которые не нашлись по маркерам (image блоки и т.д.)
    missing_ids = [bid for bid in expected_ids if bid not in segments]
    if missing_ids:
        logger.info(f"Trying fallback for {len(missing_ids)} missing blocks")
        before_count = len(segments)
        _extract_blocks_by_div_structure(
            html_text, missing_ids, set(missing_ids), segments, meta, score_cutoff
        )
        after_count = len(segments)
        logger.info(f"Fallback found {after_count - before_count} additional blocks")

    return segments, meta


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


def _propagate_stamp_data(page: dict) -> None:
    """
    Распространить данные штампа на все блоки страницы.
    Если на странице есть image блок с category_code='stamp',
    его ocr_json копируется в stamp_data всех блоков.
    """
    blocks = page.get("blocks", [])
    
    # Ищем блок штампа
    stamp_block = None
    for blk in blocks:
        if (blk.get("block_type") == "image" and 
            blk.get("category_code") == "stamp"):
            stamp_block = blk
            break
    
    if not stamp_block:
        return
    
    stamp_json = stamp_block.get("ocr_json")
    if not stamp_json:
        return
    
    # Копируем stamp_data во все блоки страницы
    for blk in blocks:
        blk["stamp_data"] = stamp_json


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
    import os
    
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
            
            # Распространение данных штампа на все блоки страницы
            _propagate_stamp_data(page)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        if missing:
            logger.warning(f"Не найдено HTML для {len(missing)} блоков. Примеры: {missing[:3]}")
        
        logger.info(f"result.json сохранён: {output_path} ({matched}/{len(expected_ids)} блоков сопоставлено)")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка объединения OCR результатов: {e}", exc_info=True)
        return False

