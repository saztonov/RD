"""
Интеграция с Marker для автоматической разметки PDF
"""

from pathlib import Path
from typing import List, Optional
from PIL import Image
import logging

from app.models import Block, BlockType, BlockSource, Page

logger = logging.getLogger(__name__)


class MarkerSegmentation:
    """Разметка PDF с использованием Marker"""
    
    def __init__(self):
        self._converter = None
        self._ensure_marker()
    
    def _ensure_marker(self):
        """Проверка и инициализация Marker"""
        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            
            if self._converter is None:
                logger.info("Инициализация Marker...")
                self._converter = PdfConverter(
                    artifact_dict=create_model_dict()
                )
                logger.info("Marker готов")
        except Exception as e:
            logger.error(f"Ошибка инициализации Marker: {e}")
            raise
    
    def segment_pdf(self, pdf_path: str, pages: List[Page], 
                    page_images: dict) -> List[Page]:
        """
        Разметка PDF с помощью Marker
        
        Args:
            pdf_path: путь к PDF файлу
            pages: список страниц Document
            page_images: словарь {page_num: PIL.Image}
        
        Returns:
            Обновленный список страниц с блоками от Marker
        """
        try:
            from marker.converters.pdf import PdfConverter
            
            logger.info(f"Запуск Marker для {pdf_path}")
            
            # Конвертация PDF
            rendered = self._converter(pdf_path)
            
            # Извлечение блоков
            for page_idx, page_data in enumerate(rendered.pages):
                if page_idx >= len(pages):
                    break
                
                page = pages[page_idx]
                page_img = page_images.get(page_idx)
                
                if not page_img:
                    continue
                
                # Извлекаем блоки из результатов Marker
                blocks = self._extract_blocks_from_marker(
                    page_data, page_idx, page.width, page.height
                )
                
                # Добавляем блоки на страницу
                page.blocks.extend(blocks)
                
                logger.info(f"Страница {page_idx}: добавлено {len(blocks)} блоков")
            
            return pages
            
        except Exception as e:
            logger.error(f"Ошибка Marker: {e}")
            raise
    
    def _extract_blocks_from_marker(self, page_data, page_idx: int, 
                                     page_width: float, page_height: float) -> List[Block]:
        """Извлечение блоков из результатов Marker"""
        blocks = []
        
        try:
            # Marker возвращает layout с блоками
            if not hasattr(page_data, 'layout') or not page_data.layout:
                return blocks
            
            for layout_block in page_data.layout:
                # Получаем координаты bbox
                if not hasattr(layout_block, 'bbox') or not layout_block.bbox:
                    continue
                
                bbox = layout_block.bbox
                x1, y1, x2, y2 = bbox.x0, bbox.y0, bbox.x1, bbox.y1
                
                # Определяем тип блока
                block_type = self._detect_block_type(layout_block)
                
                # Создаем блок
                block = Block.create(
                    page_index=page_idx,
                    coords_px=(int(x1), int(y1), int(x2), int(y2)),
                    page_width=page_width,
                    page_height=page_height,
                    category="Marker",
                    block_type=block_type,
                    source=BlockSource.AUTO
                )
                
                # Добавляем OCR текст если есть
                if hasattr(layout_block, 'text') and layout_block.text:
                    block.ocr_text = layout_block.text
                
                blocks.append(block)
        
        except Exception as e:
            logger.warning(f"Ошибка извлечения блоков: {e}")
        
        return blocks
    
    def _detect_block_type(self, layout_block) -> BlockType:
        """Определение типа блока из Marker layout"""
        try:
            if hasattr(layout_block, 'block_type'):
                marker_type = layout_block.block_type.lower()
                
                if 'table' in marker_type:
                    return BlockType.TABLE
                elif 'figure' in marker_type or 'image' in marker_type:
                    return BlockType.IMAGE
                else:
                    return BlockType.TEXT
            
            # По умолчанию текст
            return BlockType.TEXT
            
        except:
            return BlockType.TEXT


def segment_with_marker(pdf_path: str, pages: List[Page], 
                        page_images: dict) -> Optional[List[Page]]:
    """
    Функция-обертка для разметки PDF через Marker
    
    Args:
        pdf_path: путь к PDF
        pages: список страниц
        page_images: словарь изображений страниц
    
    Returns:
        Обновленный список страниц или None при ошибке
    """
    try:
        segmenter = MarkerSegmentation()
        return segmenter.segment_pdf(pdf_path, pages, page_images)
    except Exception as e:
        logger.error(f"Ошибка разметки Marker: {e}")
        return None

