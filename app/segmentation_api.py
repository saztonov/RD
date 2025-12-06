"""
Сегментация PDF через PaddleOCR PP-StructureV3 API
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
    
    # Открываем оригинальный PDF для получения размеров страниц
    original_doc = fitz.open(pdf_path)
    pdf_page_dimensions = {}  # {real_page_idx: (pdf_width, pdf_height)}
    
    try:
        # Сохраняем размеры страниц в PDF points
        for page_idx in range(len(original_doc)):
            page = original_doc[page_idx]
            pdf_page_dimensions[page_idx] = (page.rect.width, page.rect.height)
        
        # Если указан диапазон страниц, создаем временный PDF
        if page_range is not None:
            try:
                new_doc = fitz.open()
                new_doc.insert_pdf(original_doc, from_page=page_range[0], to_page=page_range[-1])
                
                # Создаем временный файл
                fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
                os.close(fd)
                
                new_doc.save(temp_pdf_path, deflate=False, garbage=0, clean=False)
                new_doc.close()
                
                target_pdf_path = temp_pdf_path
                logger.info(f"Создан временный PDF для {len(page_range)} страниц: {temp_pdf_path}")
            except Exception as e:
                logger.error(f"Ошибка создания временного PDF: {e}")
                if temp_pdf_path and os.path.exists(temp_pdf_path):
                    os.unlink(temp_pdf_path)
                raise
            finally:
                original_doc.close()
        # Если не используем диапазон, закрываем документ здесь
        else:
            original_doc.close()

        logger.info(f"Отправка PDF на API для сегментации: {target_pdf_path}")
        
        # Читаем PDF в байты
        with open(target_pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        
        # Отправляем на API
        result = segment_pdf_sync(pdf_bytes)
        
        # Обработка ответа от PP-StructureV3
        if not isinstance(result, dict) or 'pages' not in result:
            logger.error(f"Неожиданный формат ответа API: {type(result)}, keys={list(result.keys()) if isinstance(result, dict) else 'N/A'}")
            raise ValueError("API вернул некорректный формат данных")
        
        api_pages = result['pages']
        logger.info(f"API обработал PDF, страниц: {len(api_pages)}, page_count: {result.get('page_count', 'N/A')}")
        
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
            
            # Размеры страницы: приоритет у реального изображения из page_images
            if page_images and real_page_idx in page_images:
                real_img = page_images[real_page_idx]
                page_width = real_img.width
                page_height = real_img.height
                logger.debug(f"Используем размеры из page_images: {page_width}x{page_height}")
            else:
                page_width = page.width  # Fallback к размерам из Page
                page_height = page.height
                logger.debug(f"Используем размеры из Page: {page_width}x{page_height}")
            
            # Размеры страницы в PDF points
            pdf_width, pdf_height = pdf_page_dimensions.get(real_page_idx, (page_width, page_height))
            
            # Извлекаем блоки из API ответа
            new_blocks = _extract_blocks_from_api_page(
                page_data, real_page_idx, page_width, page_height, 
                pdf_width, pdf_height, category
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
                                   pdf_width: float, pdf_height: float,
                                   category: str = "") -> List[Block]:
    """
    Извлечение блоков из ответа PP-StructureV3 API
    
    Args:
        page_data: данные страницы от API (PP-StructureV3 формат)
        page_idx: индекс страницы
        page_width: ширина страницы в пикселях (рендеренное изображение)
        page_height: высота страницы в пикселях (рендеренное изображение)
        pdf_width: ширина страницы в PDF points (из оригинального документа)
        pdf_height: высота страницы в PDF points (из оригинального документа)
        category: категория для блоков
    
    Returns:
        Список блоков
    """
    blocks = []
    
    try:
        logger.debug(f"Page {page_idx} data keys: {list(page_data.keys())}")
        
        # PP-StructureV3 возвращает формат с 'blocks'
        api_blocks = page_data.get('blocks', [])
        
        if not api_blocks:
            logger.warning(f"Страница {page_idx}: нет blocks")
            return blocks
        
        logger.debug(f"Страница {page_idx}: блоков: {len(api_blocks)}")
        
        # Получаем точные размеры изображения PP-Structure из ответа API
        api_image_width = page_data.get('image_width')
        api_image_height = page_data.get('image_height')
        
        if api_image_width and api_image_height:
            # Используем точные размеры от сервера
            ppstructure_width = float(api_image_width)
            ppstructure_height = float(api_image_height)
            logger.info(f"Страница {page_idx}: используем точные размеры API: {int(ppstructure_width)}x{int(ppstructure_height)}")
        else:
            # Fallback: вычисляем размеры по известному DPI сервера (180 по умолчанию)
            # PDF points * DPI / 72 = пиксели
            server_dpi = 180  # Должен соответствовать PDF_DPI на сервере
            ppstructure_width = pdf_width * server_dpi / 72.0
            ppstructure_height = pdf_height * server_dpi / 72.0
            logger.info(f"Страница {page_idx}: вычисляем размеры PP-Structure по DPI={server_dpi}: "
                       f"{int(ppstructure_width)}x{int(ppstructure_height)}")
        
        # Вычисляем коэффициенты масштабирования от PP-Structure к нашим размерам
        scale_x = page_width / ppstructure_width if ppstructure_width > 0 else 1.0
        scale_y = page_height / ppstructure_height if ppstructure_height > 0 else 1.0
        
        logger.info(f"Страница {page_idx}: PP-Structure {int(ppstructure_width)}x{int(ppstructure_height)}, "
                   f"Our {int(page_width)}x{int(page_height)}, "
                   f"Scale {scale_x:.3f}x{scale_y:.3f}")
        
        # Счетчики для отладки
        skipped_no_bbox = 0
        processed_count = 0
        all_labels_found = set()
        
        for api_block in api_blocks:
            label = api_block.get('label', '')
            if label:
                all_labels_found.add(label)
            
            bbox = api_block.get('bbox')
            if bbox and len(bbox) == 4:
                # PP-Structure bbox в пикселях их изображения: [x1, y1, x2, y2]
                # Масштабируем к нашим размерам
                x1 = bbox[0] * scale_x
                y1 = bbox[1] * scale_y
                x2 = bbox[2] * scale_x
                y2 = bbox[3] * scale_y
                
                # Проверяем валидность координат
                if x2 > x1 and y2 > y1:
                    # Определяем тип блока из label
                    block_type = _map_ppstructure_label(label)
                    
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
                    logger.debug(f"Блок: label={label}, PP-bbox={bbox}, scaled=({int(x1)},{int(y1)},{int(x2)},{int(y2)})")
            else:
                skipped_no_bbox += 1
                logger.debug(f"Пропущен блок (нет bbox): label={label}")
    
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
        logger.info(f"Страница {page_idx}: найденные типы блоков: {sorted(all_labels_found)}")
        if skipped_no_bbox > 0:
            logger.info(f"Страница {page_idx}: пропущено без bbox: {skipped_no_bbox}")
        
    except Exception as e:
        logger.error(f"Ошибка извлечения блоков со страницы {page_idx}: {e}")
        return blocks
    
    return unique_blocks


def _map_ppstructure_label(label: str) -> BlockType:
    """
    Преобразование label от PP-StructureV3 в BlockType
    
    PP-Structure labels: header, doc_title, text, number, footer, table, image
    """
    # Точное соответствие типов
    label_mapping = {
        'text': BlockType.TEXT,
        'header': BlockType.PAGE_HEADER,
        'doc_title': BlockType.SECTION_HEADER,
        'number': BlockType.PAGE_FOOTER,
        'footer': BlockType.PAGE_FOOTER,
        'table': BlockType.TABLE,
        'image': BlockType.IMAGE,
        'figure': BlockType.FIGURE,
    }
    
    label_lower = label.lower().replace('_', '').replace('-', '')
    
    # Проверяем точное соответствие
    for key, value in label_mapping.items():
        key_normalized = key.replace('_', '').replace('-', '')
        if label_lower == key_normalized:
            return value
    
    # Fallback для неизвестных типов
    if 'table' in label_lower:
        return BlockType.TABLE
    elif 'image' in label_lower or 'figure' in label_lower:
        return BlockType.IMAGE
    elif 'header' in label_lower or 'title' in label_lower:
        return BlockType.SECTION_HEADER
    elif 'footer' in label_lower or 'number' in label_lower:
        return BlockType.PAGE_FOOTER
    
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

