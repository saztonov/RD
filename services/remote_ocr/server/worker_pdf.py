"""PDF-утилиты для OCR воркера"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Кэш размеров страниц PDF
_page_size_cache: Dict[str, Dict[int, tuple]] = {}


def get_pdf_page_size(pdf_path: str, page_index: int) -> tuple:
    """Получить размер страницы PDF (с кэшированием)"""
    global _page_size_cache
    
    if pdf_path in _page_size_cache:
        if page_index in _page_size_cache[pdf_path]:
            return _page_size_cache[pdf_path][page_index]
    else:
        _page_size_cache[pdf_path] = {}
    
    try:
        from rd_core.pdf_utils import get_pdf_page_size as rd_get_page_size
        size = rd_get_page_size(pdf_path, page_index)
        if size:
            _page_size_cache[pdf_path][page_index] = size
            return size
    except Exception as e:
        logger.warning(f"Ошибка получения размера страницы {page_index}: {e}")
    
    return (595.0, 842.0)  # A4 по умолчанию


def extract_pdfplumber_text_for_block(
    pdf_path: str, 
    page_index: int,
    coords_norm: tuple
) -> str:
    """
    Извлечь текст из области блока с помощью pdfplumber
    """
    try:
        from rd_core.pdf_utils import extract_text_for_block
        
        page_width, page_height = get_pdf_page_size(pdf_path, page_index)
        
        text = extract_text_for_block(
            pdf_path, 
            page_index, 
            coords_norm,
            page_width,
            page_height
        )
        
        logger.info(f"Извлечён текст из области блока: {len(text)} символов")
        return text
        
    except Exception as e:
        logger.warning(f"Ошибка извлечения текста pdfplumber для блока: {e}")
        return ""

