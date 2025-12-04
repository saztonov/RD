"""
Сегментация PDF через ngrok API endpoint
"""

from pathlib import Path
from typing import List, Optional, Dict, Any
import logging
import tempfile
import os
import fitz  # PyMuPDF
import httpx

from app.models import Block, BlockType, BlockSource, Page
from app.config import get_marker_base_url

logger = logging.getLogger(__name__)


async def segment_pdf_async(pdf_bytes: bytes) -> Dict[str, Any]:
    """
    Отправить PDF на сегментацию через ngrok API
    
    Args:
        pdf_bytes: байты PDF файла
    
    Returns:
        JSON структура документа от API
    """
    url = get_marker_base_url()
    files = {"file": ("document.pdf", pdf_bytes, "application/pdf")}
    
    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(url, files=files)
        response.raise_for_status()
        return response.json()


def segment_pdf_sync(pdf_bytes: bytes) -> Dict[str, Any]:
    """
    Синхронная версия сегментации PDF
    
    Args:
        pdf_bytes: байты PDF файла
    
    Returns:
        JSON структура документа от API
    """
    url = get_marker_base_url()
    files = {"file": ("document.pdf", pdf_bytes, "application/pdf")}
    
    with httpx.Client(timeout=600.0) as client:
        response = client.post(url, files=files)
        response.raise_for_status()
        result = response.json()
        
        # Детальное логирование для отладки
        if isinstance(result, dict):
            logger.debug(f"API response keys: {list(result.keys())}")
        else:
            logger.debug(f"API response type: {type(result)}")
            
        logger.debug(f"API response sample: {str(result)[:500]}")
        
        return result


def segment_with_api(pdf_path: str, pages: List[Page], 
                     page_images: Optional[dict] = None, 
                     page_range: Optional[List[int]] = None, 
                     category: str = "") -> Optional[List[Page]]:
    """
    Разметка PDF через API endpoint
    
    Args:
        pdf_path: путь к PDF
        pages: список страниц
        page_images: словарь изображений страниц (опционально)
        page_range: список индексов страниц для обработки
        category: категория для создаваемых блоков
    
    Returns:
        Обновленный список страниц или None при ошибке
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
                
                new_doc.save(temp_pdf_path, deflate=False, garbage=0, clean=False)
                new_doc.close()
                doc.close()
                
                target_pdf_path = temp_pdf_path
                logger.info(f"Создан временный PDF для {len(page_range)} страниц: {temp_pdf_path}")
            except Exception as e:
                logger.error(f"Ошибка создания временного PDF: {e}")
                if temp_pdf_path and os.path.exists(temp_pdf_path):
                    os.unlink(temp_pdf_path)
                raise

        logger.info(f"Отправка PDF на API для сегментации: {target_pdf_path}")
        
        # Читаем PDF в байты
        with open(target_pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        
        # Отправляем на API
        result = segment_pdf_sync(pdf_bytes)
        
        # Детальное логирование ответа
        if isinstance(result, dict):
            logger.info(f"API ответ: ключи={list(result.keys())}")
            # Проверяем разные форматы ответа
            if 'pages' in result:
                api_pages = result['pages']
            elif 'children' in result:
                # Формат Marker с корневым children
                logger.info("Используем 'children' как список страниц")
                api_pages = result['children']
            else:
                api_pages = []
        elif isinstance(result, list):
            logger.info(f"API ответ: список из {len(result)} элементов")
            api_pages = result
        else:
            logger.warning(f"Неожиданный формат ответа API: {type(result)}")
            api_pages = []

        logger.info(f"API обработал PDF, страниц: {len(api_pages)}")
        
        if len(api_pages) == 0:
            logger.warning(f"API вернул пустой список страниц. Полный ответ: {result}")
        
        # Извлечение блоков из каждой страницы
        # api_pages already set above
        
        for i, page_data in enumerate(api_pages):
            # Определяем реальный индекс страницы
            if page_range is not None:
                if i >= len(page_range):
                    break
                real_page_idx = page_range[i]
            else:
                real_page_idx = i
            
            # Пропускаем, если вышли за границы исходного документа
            if real_page_idx >= len(pages):
                continue
            
            page = pages[real_page_idx]
            
            # Размеры страницы
            page_width = page.width
            page_height = page.height
            
            # Извлекаем блоки из API ответа
            new_blocks = _extract_blocks_from_api_page(
                page_data, real_page_idx, page_width, page_height, category
            )
            
            # Фильтруем блоки: не добавляем те, которые пересекаются с существующими
            added_count = 0
            skipped_overlap = 0
            for new_block in new_blocks:
                if not _is_overlapping_with_existing(new_block, page.blocks):
                    page.blocks.append(new_block)
                    added_count += 1
                else:
                    skipped_overlap += 1
            
            logger.info(f"Страница {real_page_idx}: добавлено {added_count} блоков, пропущено {skipped_overlap}, всего найдено {len(new_blocks)}")
        
        return pages
        
    except Exception as e:
        logger.error(f"Ошибка API сегментации: {e}", exc_info=True)
        raise
    finally:
        # Удаляем временный файл
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            try:
                os.unlink(temp_pdf_path)
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл {temp_pdf_path}: {e}")


def _extract_blocks_from_api_page(page_data: Dict[str, Any], page_idx: int,
                                   page_width: float, page_height: float,
                                   category: str = "") -> List[Block]:
    """
    Извлечение блоков из ответа API с рекурсивной обработкой вложенных элементов
    
    Args:
        page_data: данные страницы от API
        page_idx: индекс страницы
        page_width: ширина страницы в пикселях
        page_height: высота страницы в пикселях
        category: категория для блоков
    
    Returns:
        Список блоков
    """
    blocks = []
    
    try:
        logger.debug(f"Page {page_idx} data keys: {list(page_data.keys())}")
        
        # API возвращает Marker формат с 'children'
        api_blocks = page_data.get('children', [])
        
        if not api_blocks:
            logger.warning(f"Страница {page_idx}: нет children")
            return blocks
        
        # Получаем bbox страницы для масштабирования
        page_bbox = page_data.get('bbox', [0, 0, page_width, page_height])
        api_width = page_bbox[2] - page_bbox[0]
        api_height = page_bbox[3] - page_bbox[1]
        
        # Масштабирование координат из PDF points в пиксели
        scale_x = page_width / api_width if api_width > 0 else 1.0
        scale_y = page_height / api_height if api_height > 0 else 1.0
        
        logger.debug(f"Страница {page_idx}: блоков верхнего уровня: {len(api_blocks)}, scale: {scale_x:.2f}x{scale_y:.2f}")
        
        # Исключаем только низкоуровневые элементы (Line/Span)
        EXCLUDED_TYPES = {'Line', 'Span'}
        
        # Счетчики для отладки
        skipped_by_type = {}
        skipped_no_bbox = 0
        processed_count = 0
        all_types_found = set()
        
        # Рекурсивная функция для обработки вложенных блоков
        def process_block_recursive(api_block: Dict[str, Any], depth: int = 0):
            nonlocal processed_count, skipped_by_type, skipped_no_bbox, all_types_found
            
            block_type_str = api_block.get('block_type', '')
            if block_type_str:
                all_types_found.add(block_type_str)
            
            # Пропускаем только Line и Span
            if block_type_str in EXCLUDED_TYPES:
                skipped_by_type[block_type_str] = skipped_by_type.get(block_type_str, 0) + 1
                return
            
            bbox = api_block.get('bbox')
            if bbox and len(bbox) == 4:
                # Масштабируем координаты
                x1 = bbox[0] * scale_x
                y1 = bbox[1] * scale_y
                x2 = bbox[2] * scale_x
                y2 = bbox[3] * scale_y
                
                # Проверяем валидность координат
                if x2 > x1 and y2 > y1:
                    # Определяем тип блока
                    block_type = _map_block_type(block_type_str)
                    
                    # Создаем блок
                    block = Block.create(
                        page_index=page_idx,
                        coords_px=(int(x1), int(y1), int(x2), int(y2)),
                        page_width=page_width,
                        page_height=page_height,
                        category=category,
                        block_type=block_type,
                        source=BlockSource.AUTO
                    )
                    
                    blocks.append(block)
                    processed_count += 1
                    logger.debug(f"{'  ' * depth}Добавлен блок: type={block_type_str}, coords=({int(x1)},{int(y1)},{int(x2)},{int(y2)})")
            else:
                skipped_no_bbox += 1
                logger.debug(f"{'  ' * depth}Пропущен блок (нет bbox): type={block_type_str}")
            
            # Рекурсивно обрабатываем вложенные children
            children = api_block.get('children', [])
            if children:
                logger.debug(f"{'  ' * depth}Обработка {len(children)} вложенных блоков для {block_type_str}")
                for child in children:
                    try:
                        process_block_recursive(child, depth + 1)
                    except Exception as child_err:
                        logger.warning(f"Ошибка обработки вложенного блока: {child_err}")
        
        # Обрабатываем все блоки верхнего уровня рекурсивно
        for idx, api_block in enumerate(api_blocks):
            try:
                process_block_recursive(api_block)
            except Exception as block_err:
                logger.warning(f"Ошибка блока {idx}: {block_err}")
                continue
    
        # Дедупликация блоков (удаляем полностью идентичные)
        unique_blocks = []
        seen_coords = set()
        for block in blocks:
            coords_tuple = block.coords_px
            if coords_tuple not in seen_coords:
                seen_coords.add(coords_tuple)
                unique_blocks.append(block)
        
        duplicates_removed = len(blocks) - len(unique_blocks)
        if duplicates_removed > 0:
            logger.info(f"Страница {page_idx}: удалено {duplicates_removed} дубликатов")
        
        # Логируем статистику
        logger.info(f"Страница {page_idx}: обработано {processed_count} блоков, уникальных {len(unique_blocks)}")
        logger.info(f"Страница {page_idx}: найденные типы блоков: {sorted(all_types_found)}")
        if skipped_by_type:
            logger.info(f"Страница {page_idx}: пропущено по типу: {skipped_by_type}")
        if skipped_no_bbox > 0:
            logger.info(f"Страница {page_idx}: пропущено без bbox: {skipped_no_bbox}")
        
    except Exception as e:
        logger.error(f"Ошибка извлечения блоков со страницы {page_idx}: {e}")
        return blocks
    
    return unique_blocks


def _map_block_type(type_str: str) -> BlockType:
    """
    Преобразование строки типа блока от API в BlockType
    
    Args:
        type_str: строка типа ("Text", "Table", "Image", "Figure" и т.д.)
    
    Returns:
        BlockType
    """
    type_lower = type_str.lower()
    
    if 'table' in type_lower:
        return BlockType.TABLE
    elif 'image' in type_lower or 'figure' in type_lower or 'picture' in type_lower:
        return BlockType.IMAGE
    else:
        return BlockType.TEXT


def _is_overlapping_with_existing(new_block: Block, existing_blocks: List[Block], 
                                   threshold: float = 0.7) -> bool:
    """
    Проверка пересечения нового блока с существующими.
    Возвращает True, если есть значительное пересечение.
    """
    new_coords = new_block.coords_px  # (x1, y1, x2, y2)
    
    for existing in existing_blocks:
        ex_coords = existing.coords_px
        
        # Считаем пересечение
        x_left = max(new_coords[0], ex_coords[0])
        y_top = max(new_coords[1], ex_coords[1])
        x_right = min(new_coords[2], ex_coords[2])
        y_bottom = min(new_coords[3], ex_coords[3])
        
        if x_right < x_left or y_bottom < y_top:
            continue  # Нет пересечения
        
        intersection_area = (x_right - x_left) * (y_bottom - y_top)
        new_block_area = (new_coords[2] - new_coords[0]) * (new_coords[3] - new_coords[1])
        
        if new_block_area <= 0:
            continue
        
        # Если пересечение занимает более threshold% от площади НОВОГО блока
        if (intersection_area / new_block_area) > threshold:
            return True
            
    return False

