"""Промпты и парсинг для OCR воркера"""

import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def get_image_block_prompt(
    block_prompt: Optional[dict],
    category_id: Optional[str] = None,
    category_code: Optional[str] = None,
) -> Optional[dict]:
    """
    Получить промпт для IMAGE блока с учётом категории.
    Приоритет: block.prompt > category prompt > default category
    """
    # Если блок имеет собственный промпт — используем его
    if block_prompt and (block_prompt.get("system") or block_prompt.get("user")):
        return block_prompt

    # Иначе получаем промпт из категории
    try:
        from .storage_settings import get_category_prompt

        category_prompt = get_category_prompt(category_id, category_code)
        if category_prompt:
            return category_prompt
    except Exception as e:
        logger.warning(f"Не удалось получить промпт категории: {e}")

    return None


def fill_image_prompt_variables(
    prompt_data: Optional[dict],
    doc_name: str,
    page_index: int,
    block_id: str,
    hint: Optional[str],
    pdfplumber_text: str,
    category_id: Optional[str] = None,
    category_code: Optional[str] = None,
) -> dict:
    """
    Заполнить переменные в промпте для IMAGE блока.
    Если prompt_data пуст — берёт промпт из категории.

    Переменные:
        {DOC_NAME} - имя PDF документа
        {PAGE_NUM} - номер страницы (1-based)
        {BLOCK_ID} - ID блока
        {OPERATOR_HINT} - подсказка оператора (или пустая строка)
        {PDFPLUMBER_TEXT} - извлечённый текст pdfplumber (или пустая строка)
    """
    # Получаем промпт с учётом категории
    effective_prompt = get_image_block_prompt(prompt_data, category_id, category_code)

    if not effective_prompt:
        return {
            "system": "",
            "user": "Опиши что изображено на картинке. Верни результат как JSON.",
        }

    result = {
        "system": effective_prompt.get("system", ""),
        "user": effective_prompt.get("user", ""),
    }

    variables = {
        "{DOC_NAME}": doc_name or "unknown",
        "{PAGE_NUM}": str(page_index + 1) if page_index is not None else "1",
        "{BLOCK_ID}": block_id or "",
        "{OPERATOR_HINT}": hint if hint else "",
        "{PDFPLUMBER_TEXT}": pdfplumber_text or "",
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
        json_match = re.search(r"\{[\s\S]*\}", ocr_result)
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


def build_strip_prompt(blocks: list, block_ids: Optional[List[str]] = None) -> dict:
    """
    Build prompt for TEXT block OCR.

    NOTE: Batch processing with multiple blocks is DEPRECATED.
    Each TEXT block is now processed individually.
    """
    if len(blocks) != 1:
        logger.warning(
            f"build_strip_prompt called with {len(blocks)} blocks, expected 1. "
            "Batch processing is deprecated."
        )

    # Use block's custom prompt if available
    block = blocks[0] if blocks else None
    if block and block.prompt:
        return block.prompt

    return {
        "system": "You are an expert OCR system. Extract text accurately.",
        "user": "Распознай текст на изображении. Сохрани форматирование.",
    }


def parse_batch_response_by_block_id(
    block_ids: List[str], response_text: str
) -> Dict[str, str]:
    """
    Парсинг ответа OCR для одного блока.

    NOTE: Batch processing with multiple blocks is DEPRECATED.
    Each block is now processed individually, so this function
    expects exactly one block_id.

    Returns: Dict[block_id -> text]
    """
    results: Dict[str, str] = {}

    if not block_ids:
        return results

    if len(block_ids) > 1:
        logger.warning(
            f"parse_batch_response_by_block_id called with {len(block_ids)} blocks, "
            "expected 1. Batch processing is deprecated."
        )

    if response_text is None:
        for bid in block_ids:
            results[bid] = ""
        return results

    # Для одного блока просто возвращаем весь текст
    # Убираем маркеры BLOCK если они есть (legacy)
    text = response_text.strip()
    text = re.sub(
        r"BLOCK:\s*[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{3}\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\[\[\[BLOCK_ID:\s*[a-f0-9\-]+\]\]\]\s*", "", text, flags=re.IGNORECASE
    )

    results[block_ids[0]] = text.strip()

    # Для остальных блоков (если переданы по ошибке) - пустой результат
    for bid in block_ids[1:]:
        results[bid] = ""

    return results


def parse_batch_response_by_index(
    num_blocks: int, response_text: str, block_ids: Optional[List[str]] = None
) -> Dict[int, str]:
    """
    Парсинг ответа OCR для одного блока.

    NOTE: Batch processing with multiple blocks is DEPRECATED.
    Each block is now processed individually, so this function
    expects num_blocks == 1.

    Returns: Dict[index -> text] (индекс 0-based)
    """
    results: Dict[int, str] = {}

    if response_text is None:
        for i in range(num_blocks):
            results[i] = "[Ошибка: пустой ответ OCR]"
        return results

    if num_blocks > 1:
        logger.warning(
            f"parse_batch_response_by_index called with {num_blocks} blocks, "
            "expected 1. Batch processing is deprecated."
        )

    # Для одного блока убираем маркеры если есть (legacy)
    text = response_text.strip()
    text = re.sub(
        r"BLOCK:\s*[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{3}\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\[\[\[BLOCK_ID:\s*[a-f0-9\-]+\]\]\]\s*", "", text, flags=re.IGNORECASE
    )
    results[0] = text.strip()

    # Для остальных блоков (если переданы по ошибке) - пустой результат
    for i in range(1, num_blocks):
        results[i] = ""

    return results
