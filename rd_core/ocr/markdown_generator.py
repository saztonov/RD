"""Генератор структурированного Markdown из OCR результатов"""
import logging
import os
import re
import json as json_module
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


_BLOCK_SEPARATOR_LINE_RE = re.compile(
    r'^\s*\[{2,3}\s*BLOCK\\?_ID\s*:\s*([a-f0-9\-]{36})\s*\]{2,3}\s*$',
    re.IGNORECASE,
)


def _normalize_leading_block_separators(text: str, block_id: str) -> str:
    """
    OCR иногда дублирует разделитель в начале блока (например, [[[BLOCK_ID...]]] + [[BLOCK\\_ID...]]).
    Для TEXT/TABLE оставляем ровно один канонический разделитель в начале.
    """
    lines = text.splitlines()
    i = 0
    found_sep = False

    # Пропускаем пустые строки и "похожие на разделитель" строки в начале
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if _BLOCK_SEPARATOR_LINE_RE.match(s):
            found_sep = True
            i += 1
            continue
        break

    if not found_sep:
        return text

    rest = "\n".join(lines[i:]).lstrip()
    canonical = f"[[[BLOCK_ID: {block_id}]]]"
    return canonical if not rest else f"{canonical}\n\n{rest}"


def generate_structured_markdown(
    pages: List, 
    output_path: str, 
    images_dir: str = "images", 
    project_name: str = None, 
    doc_name: str = None
) -> str:
    """
    Генерация markdown документа из размеченных блоков с учетом типов
    Блоки выводятся последовательно без разделения по страницам
    
    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения markdown файла
        images_dir: имя директории для изображений (относительно output_path)
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
            for block in page.blocks:
                all_blocks.append((page.page_number, block))
        
        all_blocks.sort(key=lambda x: (x[0], x[1].coords_px[1]))
        
        markdown_parts = []
        
        for page_num, block in all_blocks:
            if not block.ocr_text:
                continue
            
            text = block.ocr_text.strip()
            if not text:
                continue
            
            text = re.sub(r'\n{3,}', '\n\n', text)

            # TEXT/TABLE: OCR уже содержит разделители (на полосе), но иногда дублирует их.
            if block.block_type in (BlockType.TEXT, BlockType.TABLE):
                text = _normalize_leading_block_separators(text, block.id)
            
            # IMAGE блоки: добавляем разделитель (они не на полосе, OCR не содержит разделителя)
            # TEXT/TABLE: разделители уже есть в OCR тексте с изображения полосы
            if block.block_type == BlockType.IMAGE:
                block_separator = f"[[[BLOCK_ID: {block.id}]]]\n\n"
                markdown_parts.append(block_separator)
            
            if block.block_type == BlockType.IMAGE:
                analysis = None
                try:
                    json_match = re.search(r'\{[\s\S]*\}', text)
                    if json_match:
                        analysis = json_module.loads(json_match.group(0))
                    else:
                        analysis = {"raw_text": text}
                except json_module.JSONDecodeError:
                    analysis = {"raw_text": text}
                
                image_uri = ""
                mime_type = "image/png"
                if block.image_file:
                    crop_filename = Path(block.image_file).name
                    # project_name - это node_id для tree_docs
                    image_uri = f"{r2_public_url}/tree_docs/{project_name}/crops/{crop_filename}"
                    ext = Path(block.image_file).suffix.lower()
                    if ext == ".pdf":
                        mime_type = "application/pdf"
                    elif ext in (".jpg", ".jpeg"):
                        mime_type = "image/jpeg"
                
                final_json = {
                    "doc_metadata": {
                        "doc_name": doc_name or "",
                        "page": page_num + 1 if page_num is not None else None,
                        "operator_hint": block.hint or ""
                    },
                    "image": {
                        "uri": image_uri,
                        "mime_type": mime_type
                    },
                    "raw_pdfplumber_text": block.pdfplumber_text or "",
                    "analysis": analysis
                }
                
                json_str = json_module.dumps(final_json, ensure_ascii=False, indent=2)
                markdown_parts.append(f"```json\n{json_str}\n```\n\n")
            
            elif block.block_type == BlockType.TABLE:
                markdown_parts.append(f"{text}\n\n")
                
            elif block.block_type == BlockType.TEXT:
                markdown_parts.append(f"{text}\n\n")
        
        full_markdown = "".join(markdown_parts)
        output_file.write_text(full_markdown, encoding='utf-8')
        
        logger.info(f"Структурированный markdown документ сохранен: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка генерации структурированного markdown: {e}", exc_info=True)
        raise

