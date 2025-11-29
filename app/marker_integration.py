"""
Интеграция с Marker для автоматической разметки PDF
https://github.com/datalab-to/marker
"""

from pathlib import Path
from typing import List, Optional
import logging
import tempfile
import os
import fitz  # PyMuPDF

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
                    page_images: dict, page_range: Optional[List[int]] = None) -> List[Page]:
        """
        Разметка PDF с помощью Marker
        
        Args:
            pdf_path: путь к PDF файлу
            pages: список страниц Document
            page_images: словарь {page_num: PIL.Image}
            page_range: список индексов страниц для обработки (если None, обрабатываются все)
        
        Returns:
            Обновленный список страниц с блоками от Marker
        """
        temp_pdf_path = None
        target_pdf_path = pdf_path
        
        try:
            # Если указан диапазон страниц, создаем временный PDF
            if page_range is not None:
                try:
                    doc = fitz.open(pdf_path)
                    new_doc = fitz.open()
                    new_doc.insert_pdf(doc, from_page=page_range[0], to_page=page_range[-1])
                    
                    # Создаем временный файл
                    fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
                    os.close(fd)
                    
                    new_doc.save(temp_pdf_path)
                    new_doc.close()
                    doc.close()
                    
                    target_pdf_path = temp_pdf_path
                    logger.info(f"Создан временный PDF для {len(page_range)} страниц: {temp_pdf_path}")
                except Exception as e:
                    logger.error(f"Ошибка создания временного PDF: {e}")
                    if temp_pdf_path and os.path.exists(temp_pdf_path):
                        os.unlink(temp_pdf_path)
                    raise

            logger.info(f"Запуск Marker для {target_pdf_path}")
            
            # Используем build_document для получения Document с pages
            document = self._converter.build_document(target_pdf_path)
            
            logger.info(f"Marker обработал PDF, страниц: {len(document.pages)}")
            
            # Извлечение блоков из каждой страницы
            for i, page_data in enumerate(document.pages):
                # Определяем реальный индекс страницы
                if page_range is not None:
                    if i >= len(page_range):
                        break
                    real_page_idx = page_range[i]
                else:
                    real_page_idx = i
                
                # Пропускаем, если вышли за границы исходного документа (на всякий случай)
                if real_page_idx >= len(pages):
                    continue
                
                page = pages[real_page_idx]
                page_img = page_images.get(real_page_idx)
                
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
                    page_data, real_page_idx, page.width, page.height,
                    marker_width, marker_height
                )
                
                # Добавляем блоки на страницу
                if blocks:
                    page.blocks.extend(blocks)
                    logger.info(f"Страница {real_page_idx}: добавлено {len(blocks)} блоков")
            
            return pages
            
        except Exception as e:
            logger.error(f"Ошибка Marker: {e}", exc_info=True)
            raise
        finally:
            # Удаляем временный файл
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.unlink(temp_pdf_path)
                except Exception as e:
                    logger.warning(f"Не удалось удалить временный файл {temp_pdf_path}: {e}")
    
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
                    
                    # Текст НЕ извлекаем, как запрошено
                    # structure = getattr(marker_block, 'structure', None)
                    # if structure:
                    #     block.ocr_text = str(structure)
                    
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
                        page_images: dict, page_range: Optional[List[int]] = None) -> Optional[List[Page]]:
    """
    Функция-обертка для разметки PDF через Marker
    
    Args:
        pdf_path: путь к PDF
        pages: список страниц
        page_images: словарь изображений страниц
        page_range: список индексов страниц для обработки
    
    Returns:
        Обновленный список страниц или None при ошибке
    """
    try:
        segmenter = MarkerSegmentation()
        return segmenter.segment_pdf(pdf_path, pages, page_images, page_range)
    except Exception as e:
        logger.error(f"Ошибка разметки Marker: {e}")
        return None
