"""Сбор связей между блоками IMAGE→TEXT."""
from typing import Any, Dict, List

from .html_converter import html_to_markdown
from .formatter import process_ocr_content


def collect_image_text_links_from_pages(pages: List) -> Dict[str, str]:
    """
    Собрать map связанных пар IMAGE→TEXT.

    Логика: Если TEXT блок имеет linked_block_id, который указывает на IMAGE блок,
    то TEXT - это OCR-описание для IMAGE и должен быть встроен в IMAGE блок.

    Returns:
        Dict[image_block_id, text_block_id] - map для встраивания TEXT в IMAGE
    """
    from rd_core.models.enums import BlockType

    # Сначала собираем все блоки в единый индекс по ID
    all_blocks: Dict[str, Any] = {}
    for page in pages:
        for block in page.blocks:
            all_blocks[block.id] = block

    # Ищем TEXT блоки, связанные с IMAGE блоками
    image_to_text: Dict[str, str] = {}

    for page in pages:
        for block in page.blocks:
            if block.block_type == BlockType.TEXT:
                linked_id = getattr(block, "linked_block_id", None)
                if linked_id and linked_id in all_blocks:
                    linked_block = all_blocks[linked_id]
                    if linked_block.block_type == BlockType.IMAGE:
                        # TEXT связан с IMAGE - запоминаем
                        image_to_text[linked_id] = block.id

    return image_to_text


def collect_image_text_links_from_result(pages: List[Dict]) -> Dict[str, str]:
    """
    Собрать map связанных пар IMAGE→TEXT из result dict.

    Returns:
        Dict[image_block_id, text_block_id] - map для встраивания TEXT в IMAGE
    """
    # Сначала собираем все блоки в единый индекс по ID
    all_blocks: Dict[str, Dict] = {}
    for page in pages:
        for blk in page.get("blocks", []):
            block_id = blk.get("id", "")
            if block_id:
                all_blocks[block_id] = blk

    # Ищем TEXT блоки, связанные с IMAGE блоками
    image_to_text: Dict[str, str] = {}

    for page in pages:
        for blk in page.get("blocks", []):
            block_type = blk.get("block_type", "").lower()
            if block_type == "text":
                linked_id = blk.get("linked_block_id")
                if linked_id and linked_id in all_blocks:
                    linked_blk = all_blocks[linked_id]
                    if linked_blk.get("block_type", "").lower() == "image":
                        # TEXT связан с IMAGE - запоминаем
                        image_to_text[linked_id] = blk.get("id", "")

    return image_to_text


def get_text_block_content(
    block_id: str, all_blocks: Dict[str, Any], is_dict: bool = False
) -> str:
    """
    Получить обработанное содержимое TEXT блока по ID.

    Args:
        block_id: ID TEXT блока
        all_blocks: словарь всех блоков {id: block}
        is_dict: True если работаем с dict структурой, False если с объектами

    Returns:
        Обработанный текст для встраивания в IMAGE блок
    """
    if block_id not in all_blocks:
        return ""

    block = all_blocks[block_id]

    if is_dict:
        ocr_html = block.get("ocr_html", "")
        ocr_text = block.get("ocr_text", "")
        if ocr_html:
            return html_to_markdown(ocr_html)
        elif ocr_text:
            return process_ocr_content(ocr_text)
    else:
        ocr_text = getattr(block, "ocr_text", None)
        if ocr_text:
            return process_ocr_content(ocr_text)

    return ""
