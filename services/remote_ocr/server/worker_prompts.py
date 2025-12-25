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


def parse_batch_response_by_block_id(response_text: str, block_ids: List[str]) -> Dict[int, str]:
    """
    Парсинг ответа по разделителям [[[BLOCK_ID: uuid]]].
    Returns: Dict[index -> text] (индекс 0-based, соответствует порядку в block_ids)
    """
    results: Dict[int, str] = {}
    num_blocks = len(block_ids)
    
    if response_text is None:
        for i in range(num_blocks):
            results[i] = "[Ошибка: пустой ответ OCR]"
        return results
    
    # Паттерн для разделителей [[[BLOCK_ID: uuid]]]
    block_id_pattern = r'\[\[\[BLOCK_ID:\s*([a-f0-9\-]+)\]\]\]'
    
    # Разбиваем по разделителям, сохраняя UUID
    parts = re.split(block_id_pattern, response_text)
    
    # parts: [before_first, uuid1, text1, uuid2, text2, ...]
    block_id_to_text: Dict[str, str] = {}
    
    for i in range(1, len(parts) - 1, 2):
        try:
            uuid = parts[i].strip()
            text = parts[i + 1].strip() if i + 1 < len(parts) else ""
            # Убираем возможные маркеры PageHeader и лишние переносы
            text = re.sub(r'^#+\s*$', '', text, flags=re.MULTILINE).strip()
            block_id_to_text[uuid] = text
        except IndexError:
            continue
    
    if block_id_to_text:
        # Маппим UUID на индексы
        for idx, bid in enumerate(block_ids):
            if bid in block_id_to_text:
                results[idx] = block_id_to_text[bid]
            else:
                results[idx] = ""
                logger.warning(f"BLOCK_ID {bid} не найден в ответе OCR")
        return results
    
    # Fallback: если разделители не найдены, используем старый метод
    logger.warning("Разделители [[[BLOCK_ID:]]] не найдены, fallback на parse_batch_response_by_index")
    return parse_batch_response_by_index(num_blocks, response_text)


def parse_batch_response_by_index(num_blocks: int, response_text: str) -> Dict[int, str]:
    """
    Парсинг ответа с маркерами [1], [2], ...
    Returns: Dict[index -> text] (индекс 0-based)
    """
    results: Dict[int, str] = {}
    
    if response_text is None:
        for i in range(num_blocks):
            results[i] = "[Ошибка: пустой ответ OCR]"
        return results
    
    if num_blocks == 1:
        # Для одного блока убираем разделитель [[[BLOCK_ID:]]] если есть
        text = re.sub(r'\[\[\[BLOCK_ID:\s*[a-f0-9\-]+\]\]\]\s*', '', response_text).strip()
        results[0] = text
        return results
    
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

