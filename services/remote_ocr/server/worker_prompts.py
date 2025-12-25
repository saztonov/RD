"""Промпты и парсинг для OCR воркера"""

import re
import json
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


def fill_image_prompt_variables(
    prompt_data: Optional[dict],
    doc_name: str,
    page_index: int,
    block_id: str,
    hint: Optional[str],
    pdfplumber_text: str
) -> dict:
    """
    Заполнить переменные в промпте для IMAGE блока
    
    Переменные:
        {DOC_NAME} - имя PDF документа
        {PAGE_OR_NULL} - номер страницы (1-based) или "null"
        {TILE_ID_OR_NULL} - ID блока или "null"
        {TILE_HINT_OR_NULL} - подсказка пользователя или "null"
        {OPERATOR_HINT_OR_EMPTY} - подсказка пользователя или пустая строка
        {PDFPLUMBER_TEXT_OR_EMPTY} - извлечённый текст pdfplumber
    """
    if not prompt_data:
        return {"system": "", "user": "Опиши что изображено на картинке."}
    
    result = {
        "system": prompt_data.get("system", ""),
        "user": prompt_data.get("user", "")
    }
    
    variables = {
        "{DOC_NAME}": doc_name or "unknown",
        "{PAGE_OR_NULL}": str(page_index + 1) if page_index is not None else "null",
        "{TILE_ID_OR_NULL}": block_id or "null",
        "{TILE_HINT_OR_NULL}": hint if hint else "null",
        "{OPERATOR_HINT_OR_EMPTY}": hint if hint else "",
        "{PDFPLUMBER_TEXT_OR_EMPTY}": pdfplumber_text or "",
        "{PDFPLUMBER_TEXT_RAW}": pdfplumber_text or "",
    }
    
    for key, value in variables.items():
        result["system"] = result["system"].replace(key, value)
        result["user"] = result["user"].replace(key, value)
    
    return result


def inject_pdfplumber_to_ocr_text(ocr_result: str, pdfplumber_text: str) -> str:
    """
    Вставить pdfplumber текст в поле ocr_text результата OCR.
    """
    if not pdfplumber_text or not pdfplumber_text.strip():
        return ocr_result
    
    if not ocr_result:
        return ocr_result
    
    try:
        json_match = re.search(r'\{[\s\S]*\}', ocr_result)
        if json_match:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            
            if "ocr_text" in data:
                data["ocr_text"] = pdfplumber_text.strip()
                new_json = json.dumps(data, ensure_ascii=False, indent=2)
                
                if ocr_result.strip().startswith("```"):
                    return f"```json\n{new_json}\n```"
                return new_json
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning(f"Не удалось вставить pdfplumber текст в JSON: {e}")
    
    return ocr_result


def build_strip_prompt(blocks: list) -> dict:
    """
    Построить промпт для batch запроса (полоса TEXT/TABLE блоков).
    Формат ответа: [1] результат первого ... [N] результат N-го
    """
    if len(blocks) == 1:
        block = blocks[0]
        if block.prompt:
            return block.prompt
        return {
            "system": "You are an expert OCR system. Extract text accurately.",
            "user": "Распознай текст на изображении. Сохрани форматирование."
        }
    
    system = "You are an expert OCR system. Extract text from each block accurately."
    user = "Распознай текст на изображении."
    
    batch_instruction = (
        f"\n\nНа изображении {len(blocks)} блоков, расположенных вертикально (сверху вниз).\n"
        f"Распознай каждый блок ОТДЕЛЬНО.\n"
        f"Формат ответа:\n"
    )
    for i in range(1, len(blocks) + 1):
        batch_instruction += f"[{i}] <результат блока {i}>\n"
    
    batch_instruction += "\nНе объединяй блоки. Каждый блок — отдельный фрагмент документа."
    
    return {
        "system": system,
        "user": user + batch_instruction
    }


def parse_batch_response_by_block_id(block_ids: List[str], response_text: str) -> Dict[str, str]:
    """
    Парсинг ответа с разделителями [[[BLOCK_ID: uuid]]].
    Returns: Dict[block_id -> text]
    """
    results: Dict[str, str] = {}
    
    if response_text is None:
        for bid in block_ids:
            results[bid] = ""
        return results
    
    # Ищем все разделители [[[BLOCK_ID: uuid]]] (учитываем экранирование \_)
    pattern = r'\[\[\[BLOCK\\?_ID:\s*([a-f0-9\-]+)\]\]\]'
    matches = list(re.finditer(pattern, response_text, re.IGNORECASE))
    
    if matches:
        logger.info(f"Найдено {len(matches)} разделителей BLOCK_ID в OCR ответе")
        
        for i, match in enumerate(matches):
            block_id = match.group(1)
            # Включаем сам разделитель в текст блока
            start_pos = match.start()
            
            # Определяем конец текста блока
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(response_text)
            
            block_text = response_text[start_pos:end_pos].strip()
            results[block_id] = block_text
        
        # Заполняем пустые для блоков без результата
        for bid in block_ids:
            if bid not in results:
                results[bid] = ""
                logger.warning(f"BLOCK_ID {bid} не найден в OCR ответе")
        
        return results
    
    # Fallback: если разделителей нет, весь текст первому блоку
    logger.warning(f"Разделители BLOCK_ID не найдены, текст целиком первому блоку")
    for i, bid in enumerate(block_ids):
        if i == 0:
            results[bid] = response_text.strip()
        else:
            results[bid] = ""
    
    return results


def parse_batch_response_by_index(num_blocks: int, response_text: str, block_ids: Optional[List[str]] = None) -> Dict[int, str]:
    """
    Парсинг ответа с маркерами [1], [2], ... или [[[BLOCK_ID: uuid]]]
    Returns: Dict[index -> text] (индекс 0-based)
    """
    results: Dict[int, str] = {}
    
    if response_text is None:
        for i in range(num_blocks):
            results[i] = "[Ошибка: пустой ответ OCR]"
        return results
    
    if num_blocks == 1:
        # Для одного блока сохраняем разделитель если есть
        results[0] = response_text.strip()
        return results
    
    # Сначала пробуем парсить по [[[BLOCK_ID: uuid]]] (учитываем экранирование \_)
    block_id_pattern = r'\[\[\[BLOCK\\?_ID:\s*([a-f0-9\-]+)\]\]\]'
    block_id_matches = list(re.finditer(block_id_pattern, response_text, re.IGNORECASE))
    
    if block_id_matches and len(block_id_matches) >= num_blocks:
        logger.info(f"Парсинг по BLOCK_ID разделителям: найдено {len(block_id_matches)}")
        
        for i, match in enumerate(block_id_matches):
            if i >= num_blocks:
                break
            
            # Включаем сам разделитель в текст блока
            start_pos = match.start()
            if i + 1 < len(block_id_matches):
                end_pos = block_id_matches[i + 1].start()
            else:
                end_pos = len(response_text)
            
            block_text = response_text[start_pos:end_pos].strip()
            results[i] = block_text
        
        # Заполняем оставшиеся
        for i in range(num_blocks):
            if i not in results:
                results[i] = ""
        
        return results
    
    # Fallback: парсим по [1], [2], ...
    parts = re.split(r'\n?\[(\d+)\]\s*', response_text)
    
    parsed = {}
    for i in range(1, len(parts) - 1, 2):
        try:
            idx = int(parts[i]) - 1
            text = parts[i + 1].strip()
            if 0 <= idx < num_blocks:
                parsed[idx] = text
        except (ValueError, IndexError):
            continue
    
    if not parsed:
        alt_parts = re.split(r'\n{3,}|(?:\n-{3,}\n)', response_text.strip())
        if len(alt_parts) >= num_blocks:
            for i in range(num_blocks):
                results[i] = alt_parts[i].strip()
            return results
        for i in range(num_blocks):
            if i == 0:
                results[i] = response_text.strip()
            else:
                results[i] = ""
        logger.warning(f"Batch response без маркеров [N], весь текст присвоен первому элементу")
        return results
    
    for i in range(num_blocks):
        if i in parsed:
            results[i] = parsed[i]
        else:
            results[i] = ""
            logger.warning(f"Элемент {i} не найден в batch response")
    
    return results

