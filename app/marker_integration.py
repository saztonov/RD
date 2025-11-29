"""
Интеграция с Marker для автоматической разметки PDF
https://github.com/datalab-to/marker
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
                # Загружаем модели
                models = create_model_dict()
                self._converter = PdfConverter(artifact_dict=models)
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
            logger.info(f"Запуск Marker для {pdf_path}")
            
            # Используем build_document для получения Document с pages
            document = self._converter.build_document(pdf_path)
            
            logger.info(f"Marker обработал PDF, страниц: {len(document.pages)}")
            
            # Извлечение блоков из каждой страницы
            for page_idx, page_data in enumerate(document.pages):
                if page_idx >= len(pages):
                    break
                
                page = pages[page_idx]
                page_img = page_images.get(page_idx)
                
                if not page_img:
                    continue
                
                # Получаем размер страницы из Marker (PDF points)
                marker_page_bbox = page_data.polygon.bbox if page_data.polygon else None
                if marker_page_bbox:
                    marker_width = marker_page_bbox[2] - marker_page_bbox[0]
                    marker_height = marker_page_bbox[3] - marker_page_bbox[1]
                else:
                    marker_width = page.width
                    marker_height = page.height
                
                # Извлекаем блоки из страницы
                blocks = self._extract_blocks_from_page(
                    page_data, page_idx, page.width, page.height,
                    marker_width, marker_height
                )
                
                # Добавляем блоки на страницу
                if blocks:
                    page.blocks.extend(blocks)
                    logger.info(f"Страница {page_idx}: добавлено {len(blocks)} блоков")
            
            return pages
            
        except Exception as e:
            logger.error(f"Ошибка Marker: {e}", exc_info=True)
            raise
    
    # Типы блоков верхнего уровня (игнорируем Line, Span, Word и т.д.)
    TOP_LEVEL_BLOCK_TYPES = {
        'Text', 'Table', 'Figure', 'Picture', 'Caption', 'Code', 
        'Equation', 'SectionHeader', 'ListItem', 'PageHeader', 
        'PageFooter', 'Footnote', 'Form', 'Handwriting', 'Reference',
        'TableOfContents', 'ComplexRegion', 'InlineMath'
    }
    
    def _extract_blocks_from_page(self, page_data, page_idx: int, 
                                   page_width: float, page_height: float,
                                   marker_width: float, marker_height: float) -> List[Block]:
        """Извлечение блоков из страницы Marker (PageGroup)"""
        blocks = []
        
        # Коэффициенты масштабирования из координат Marker в пиксели изображения
        scale_x = page_width / marker_width if marker_width > 0 else 1.0
        scale_y = page_height / marker_height if marker_height > 0 else 1.0
        
        try:
            # PageGroup содержит children с блоками
            children = getattr(page_data, 'children', None)
            if not children:
                logger.warning(f"Страница {page_idx}: нет children")
                return blocks
            
            # Фильтруем только блоки верхнего уровня
            top_level_blocks = []
            for child in children:
                block_type_name = type(child).__name__
                if block_type_name in self.TOP_LEVEL_BLOCK_TYPES:
                    top_level_blocks.append(child)
            
            logger.debug(f"Страница {page_idx}: блоков: {len(top_level_blocks)} из {len(children)}, scale: {scale_x:.2f}x{scale_y:.2f}")
            
            for idx, marker_block in enumerate(top_level_blocks):
                try:
                    # Получаем polygon (PolygonBox)
                    polygon = getattr(marker_block, 'polygon', None)
                    if not polygon:
                        continue
                    
                    # PolygonBox имеет метод bbox -> [x1, y1, x2, y2]
                    bbox = polygon.bbox
                    if bbox and len(bbox) == 4:
                        # Масштабируем координаты
                        x1 = bbox[0] * scale_x
                        y1 = bbox[1] * scale_y
                        x2 = bbox[2] * scale_x
                        y2 = bbox[3] * scale_y
                    else:
                        continue
                    
                    # Определяем тип блока
                    block_type = self._detect_block_type(marker_block)
                    
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
                    
                    # Добавляем текст если есть (из structure)
                    structure = getattr(marker_block, 'structure', None)
                    if structure:
                        block.ocr_text = str(structure)
                    
                    blocks.append(block)
                    
                except Exception as block_err:
                    logger.warning(f"Ошибка блока {idx}: {block_err}")
                    continue
        
        except Exception as e:
            logger.error(f"Ошибка извлечения блоков со страницы {page_idx}: {e}")
        
        return blocks
    
    def _detect_block_type(self, layout_block) -> BlockType:
        """Определение типа блока из Marker"""
        try:
            # Проверяем атрибут block_type
            if hasattr(layout_block, 'block_type'):
                btype = str(layout_block.block_type).lower()
                
                if 'table' in btype:
                    return BlockType.TABLE
                elif 'figure' in btype or 'image' in btype or 'picture' in btype:
                    return BlockType.IMAGE
            
            # Проверяем label
            if hasattr(layout_block, 'label'):
                label = str(layout_block.label).lower()
                
                if 'table' in label:
                    return BlockType.TABLE
                elif 'figure' in label or 'image' in label:
                    return BlockType.IMAGE
            
            # По умолчанию текст
            return BlockType.TEXT
            
        except Exception as e:
            logger.debug(f"Ошибка определения типа блока: {e}")
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

