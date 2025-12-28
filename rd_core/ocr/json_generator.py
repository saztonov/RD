"""Генератор HTML из OCR результатов"""
import logging
import os
import re
import json as json_module
from datetime import datetime
from pathlib import Path
from typing import List, Any

logger = logging.getLogger(__name__)


def _extract_html_from_ocr_text(ocr_text: str) -> str:
    """
    Извлечь HTML из ocr_text.
    
    ocr_text может содержать:
    - Чистый HTML от Datalab
    - JSON с полем html или children[].html
    - Просто текст (fallback)
    """
    if not ocr_text:
        return ""
    
    text = ocr_text.strip()
    if not text:
        return ""
    
    # Если начинается с HTML тега - возвращаем как есть
    if text.startswith('<'):
        return text
    
    # Пробуем распарсить как JSON
    try:
        parsed = json_module.loads(text)
        html = _extract_html_from_parsed(parsed)
        if html:
            return html
    except json_module.JSONDecodeError:
        pass
    
    # Fallback: возвращаем как есть (экранируем HTML)
    return f"<pre>{_escape_html(text)}</pre>"


def _extract_html_from_parsed(data: Any) -> str:
    """Извлечь HTML из распарсенного JSON."""
    html_parts = []
    
    if isinstance(data, dict):
        # Если есть html на этом уровне
        if "html" in data and isinstance(data["html"], str):
            html_parts.append(data["html"])
        elif "children" in data and isinstance(data["children"], list):
            for child in data["children"]:
                html_parts.append(_extract_html_from_parsed(child))
    elif isinstance(data, list):
        for item in data:
            html_parts.append(_extract_html_from_parsed(item))
    
    return "".join(html_parts)


def _escape_html(text: str) -> str:
    """Экранировать HTML спецсимволы."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def generate_html_from_pages(
    pages: List,
    output_path: str,
    doc_name: str = None,
    project_name: str = None
) -> str:
    """
    Генерация итогового HTML файла из OCR результатов.
    
    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения HTML файла
        doc_name: имя документа для заголовка
        project_name: имя проекта для ссылок на R2
    
    Returns:
        Путь к сохранённому файлу
    """
    try:
        from rd_core.models import BlockType
        
        r2_public_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        title = doc_name or "OCR Result"
        
        html_parts = [f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - OCR</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 2rem; line-height: 1.6; }}
        .block {{ margin: 1.5rem 0; padding: 1rem; border-left: 3px solid #3498db; background: #f8f9fa; }}
        .block-header {{ font-size: 0.8rem; color: #666; margin-bottom: 0.5rem; }}
        .block-content {{ }}
        .block-type-text {{ border-left-color: #2ecc71; }}
        .block-type-table {{ border-left-color: #e74c3c; }}
        .block-type-image {{ border-left-color: #9b59b6; }}
        table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0; }}
        th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
        th {{ background: #f0f0f0; }}
        img {{ max-width: 100%; height: auto; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; }}
        pre {{ white-space: pre-wrap; word-wrap: break-word; background: #fff; padding: 0.5rem; }}
    </style>
</head>
<body>
<h1>{title}</h1>
<p>Сгенерировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
"""]
        
        block_count = 0
        for page in pages:
            for idx, block in enumerate(page.blocks):
                if not block.ocr_text:
                    continue
                
                block_count += 1
                block_type = block.block_type.value
                page_num = page.page_number + 1 if page.page_number is not None else ""
                
                html_parts.append(f'<div class="block block-type-{block_type}">')
                html_parts.append(f'<div class="block-header">Блок #{idx + 1} (стр. {page_num}) | Тип: {block_type} | ID: {block.id[:8]}...</div>')
                html_parts.append('<div class="block-content">')
                
                # Извлекаем HTML из ocr_text
                block_html = _extract_html_from_ocr_text(block.ocr_text)
                html_parts.append(block_html)
                
                # Для IMAGE блоков добавляем ссылку на изображение
                if block.block_type == BlockType.IMAGE and block.image_file:
                    crop_filename = Path(block.image_file).name
                    if project_name:
                        image_uri = f"{r2_public_url}/tree_docs/{project_name}/crops/{crop_filename}"
                        html_parts.append(f'<p><a href="{image_uri}" target="_blank">Открыть изображение</a></p>')
                
                html_parts.append('</div></div>')
        
        html_parts.append("</body></html>")
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))
        
        logger.info(f"HTML файл сохранён: {output_file} ({block_count} блоков)")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка генерации HTML: {e}", exc_info=True)
        raise
