"""
Сегментация PDF через API: Paddle PP-StructureV3 и Surya Layout
"""

from pathlib import Path
from typing import List, Optional, Dict, Any
import logging
import tempfile
import os
import fitz  # PyMuPDF
import httpx

from app.models import Block, BlockType, BlockSource, Page
from app.config import get_layout_url

logger = logging.getLogger(__name__)


def segment_pdf_layout(pdf_bytes: bytes) -> Dict[str, Any]:
    """Сегментация через /layout (возвращает Surya + Paddle данные)"""
    url = get_layout_url()
    files = {"file": ("document.pdf", pdf_bytes, "application/pdf")}
    
    with httpx.Client(timeout=600.0) as client:
        response = client.post(url, files=files)
        response.raise_for_status()
        result = response.json()
        logger.debug(f"Layout API response keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
        return result


# Алиас для обратной совместимости
def segment_pdf_sync(pdf_bytes: bytes) -> Dict[str, Any]:
    return segment_pdf_layout(pdf_bytes)


def segment_with_api(pdf_path: str, pages: List[Page], 
                     page_images: Optional[dict] = None, 
                     page_range: Optional[List[int]] = None, 
                     category: str = "",
                     engine: str = "paddle") -> Optional[List[Page]]:
    """
    Разметка PDF через API endpoint
    
    Args:
        pdf_path: путь к PDF
        pages: список страниц
        page_images: словарь изображений страниц (опционально)
        page_range: список индексов страниц для обработки
        category: категория для создаваемых блоков
        engine: "paddle" (PP-StructureV3) или "surya" (Surya+Paddle)
    
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
        
        # Отправляем на API (один endpoint для обоих движков)
        result = segment_pdf_layout(pdf_bytes)
        
        # Обработка ответа
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
            
            # Извлекаем блоки из API ответа (один endpoint, разный парсинг)
            if engine == "surya":
                new_blocks = _extract_blocks_from_surya_page(
                    page_data, real_page_idx, page_width, page_height, category
                )
            else:
                new_blocks = _extract_blocks_from_paddle_raw(
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


def _extract_blocks_from_surya_page(page_data: Dict[str, Any], page_idx: int,
                                     page_width: float, page_height: float,
                                     category: str = "") -> List[Block]:
    """Извлечение блоков из ответа Surya /layout API"""
    blocks = []
    
    try:
        api_blocks = page_data.get('blocks', [])
        if not api_blocks:
            logger.warning(f"Страница {page_idx}: нет blocks от Surya")
            return blocks
        
        # Размеры из ответа API (размер изображения на сервере)
        api_width = page_data.get('width', page_width)
        api_height = page_data.get('height', page_height)
        
        # Проверяем image_bbox из surya_page_raw - Surya может использовать другой размер внутренне
        surya_raw = page_data.get('surya_page_raw') or {}
        image_bbox = surya_raw.get('image_bbox')
        if image_bbox and len(image_bbox) == 4:
            # image_bbox = [x1, y1, x2, y2], обычно [0, 0, width, height]
            surya_internal_width = image_bbox[2] - image_bbox[0]
            surya_internal_height = image_bbox[3] - image_bbox[1]
            if surya_internal_width > 0 and surya_internal_height > 0:
                # Surya вернул координаты относительно этого размера
                logger.info(f"Страница {page_idx}: Surya image_bbox = {image_bbox}")
                api_width = surya_internal_width
                api_height = surya_internal_height
        
        scale_x = page_width / api_width if api_width > 0 else 1.0
        scale_y = page_height / api_height if api_height > 0 else 1.0
        
        logger.info(f"Страница {page_idx}: Surya {int(api_width)}x{int(api_height)}, "
                   f"Our {int(page_width)}x{int(page_height)}, Scale {scale_x:.3f}x{scale_y:.3f}")
        
        # Padding снизу для компенсации обрезки (в % от высоты блока)
        BOTTOM_PADDING_PERCENT = 0.05  # 5% от высоты блока
        
        skipped_labels = 0
        for api_block in api_blocks:
            bbox = api_block.get('bbox')
            if not bbox or len(bbox) != 4:
                continue
            
            # Label из surya
            surya_info = api_block.get('surya', {})
            label = surya_info.get('label', '')
            
            # Пропускаем строки и мелкие элементы - оставляем только блоки
            if not _is_block_label(label):
                skipped_labels += 1
                continue
            
            # bbox уже в формате [x1, y1, x2, y2]
            x1 = bbox[0] * scale_x
            y1 = bbox[1] * scale_y
            x2 = bbox[2] * scale_x
            y2 = bbox[3] * scale_y
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            block_type = _map_surya_label(label)
            
            # Добавляем padding снизу для текста и таблиц
            if block_type in (BlockType.TEXT, BlockType.TABLE):
                block_height = y2 - y1
                padding = block_height * BOTTOM_PADDING_PERCENT
                y2 = min(y2 + padding, page_height)  # Не выходим за границы
            
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
        
        if skipped_labels > 0:
            logger.info(f"Страница {page_idx}: пропущено {skipped_labels} строчных элементов")
        
        logger.info(f"Страница {page_idx}: извлечено {len(blocks)} блоков от Surya")
        
    except Exception as e:
        logger.error(f"Ошибка извлечения блоков Surya на странице {page_idx}: {e}")
    
    return blocks


def _map_surya_label(label: str) -> BlockType:
    """Преобразование label от Surya в BlockType"""
    label_lower = (label or '').lower().strip()
    
    # Таблицы
    if label_lower in {'table', 'table-of-contents'}:
        return BlockType.TABLE
    
    # Картинки/графика
    if label_lower in {'picture', 'figure', 'image', 'chart'}:
        return BlockType.IMAGE
    
    # Всё остальное - текст
    return BlockType.TEXT


# Labels от Surya которые являются БЛОКАМИ (не строками)
SURYA_BLOCK_LABELS = {
    'text', 'title', 'section-header', 'page-header', 'page-footer',
    'table', 'table-of-contents',
    'picture', 'figure', 'image', 'chart',
    'list', 'list-item',
    'caption', 'footnote',
    'form', 'key-value-region',
}

# Labels которые нужно игнорировать (строки, мелкие элементы)
SURYA_SKIP_LABELS = {
    'line', 'span', 'word', 'textinlinemath', 'text-inline-math',
    'formula', 'page-number', 'handwriting',
}


def _is_block_label(label: str) -> bool:
    """Проверка, является ли label блочным элементом (не строкой)"""
    label_lower = (label or '').lower().strip()
    
    # Пропускаем явно мелкие элементы
    if label_lower in SURYA_SKIP_LABELS:
        return False
    
    # Принимаем известные блочные элементы
    if label_lower in SURYA_BLOCK_LABELS:
        return True
    
    # По умолчанию принимаем неизвестные label как блоки
    return True


def _extract_blocks_from_paddle_raw(page_data: Dict[str, Any], page_idx: int,
                                     page_width: float, page_height: float,
                                     category: str = "") -> List[Block]:
    """Извлечение блоков из paddle_page_raw в ответе /layout"""
    blocks = []
    
    try:
        paddle_raw = page_data.get('paddle_page_raw', {})
        api_blocks = paddle_raw.get('blocks', [])
        
        if not api_blocks:
            logger.warning(f"Страница {page_idx}: нет blocks от Paddle")
            return blocks
        
        # Размеры из paddle_page_raw
        api_width = paddle_raw.get('image_width', page_width)
        api_height = paddle_raw.get('image_height', page_height)
        
        scale_x = page_width / api_width if api_width > 0 else 1.0
        scale_y = page_height / api_height if api_height > 0 else 1.0
        
        logger.info(f"Страница {page_idx}: Paddle {int(api_width)}x{int(api_height)}, "
                   f"Our {int(page_width)}x{int(page_height)}, Scale {scale_x:.3f}x{scale_y:.3f}")
        
        for api_block in api_blocks:
            bbox = api_block.get('bbox')
            if not bbox:
                continue
            
            # Paddle bbox может быть в формате 4 точек [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            if len(bbox) == 4 and isinstance(bbox[0], (list, tuple)):
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            elif len(bbox) == 4:
                x1, y1, x2, y2 = bbox
            else:
                continue
            
            # Масштабируем
            x1 = x1 * scale_x
            y1 = y1 * scale_y
            x2 = x2 * scale_x
            y2 = y2 * scale_y
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            label = api_block.get('label', '')
            block_type = _map_ppstructure_label(label)
            
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
        
        logger.info(f"Страница {page_idx}: извлечено {len(blocks)} блоков от Paddle")
        
    except Exception as e:
        logger.error(f"Ошибка извлечения блоков Paddle на странице {page_idx}: {e}")
    
    return blocks


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
                    
                    # Детальное логирование для отладки маппинга
                    logger.debug(f"Label mapping: '{label}' -> {block_type.value}")
                    
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
        logger.info(f"Страница {page_idx}: найденные labels от API: {sorted(all_labels_found)}")
        
        # Статистика по типам после маппинга
        type_counts = {}
        for block in unique_blocks:
            bt = block.block_type.value
            type_counts[bt] = type_counts.get(bt, 0) + 1
        logger.info(f"Страница {page_idx}: блоки по типам: {type_counts}")
        
        if skipped_no_bbox > 0:
            logger.info(f"Страница {page_idx}: пропущено без bbox: {skipped_no_bbox}")
        
    except Exception as e:
        logger.error(f"Ошибка извлечения блоков со страницы {page_idx}: {e}")
        return blocks
    
    return unique_blocks


def _map_ppstructure_label(label: str) -> BlockType:
    """
    Преобразование label от PP-StructureV3/PP-DocLayout в BlockType (3 типа: TEXT, TABLE, IMAGE)
    """
    label_lower = label.lower().strip()
    
    # Картинки/графика -> IMAGE
    image_labels = {'figure', 'image', 'picture', 'chart', 'seal', 'signature', 'logo', 'icon', 'diagram', 'photo'}
    if label_lower in image_labels:
        return BlockType.IMAGE
    
    # Таблицы -> TABLE
    if label_lower == 'table':
        return BlockType.TABLE
    
    # Fallback по подстрокам
    if any(kw in label_lower for kw in ['figure', 'image', 'picture', 'photo', 'chart', 'diagram', 'seal', 'logo', 'icon']):
        return BlockType.IMAGE
    
    if 'table' in label_lower and 'caption' not in label_lower:
        return BlockType.TABLE
    
    # Всё остальное -> TEXT
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


def _calculate_iou(coords1: tuple, coords2: tuple) -> float:
    """Вычислить IoU (Intersection over Union) двух bbox"""
    x1 = max(coords1[0], coords2[0])
    y1 = max(coords1[1], coords2[1])
    x2 = min(coords1[2], coords2[2])
    y2 = min(coords1[3], coords2[3])
    
    if x2 <= x1 or y2 <= y1:
        return 0.0
    
    intersection = (x2 - x1) * (y2 - y1)
    area1 = (coords1[2] - coords1[0]) * (coords1[3] - coords1[1])
    area2 = (coords2[2] - coords2[0]) * (coords2[3] - coords2[1])
    union = area1 + area2 - intersection
    
    return intersection / union if union > 0 else 0.0


def _get_block_area(block: Block) -> float:
    """Площадь блока"""
    c = block.coords_px
    return (c[2] - c[0]) * (c[3] - c[1])


def _get_block_priority(block: Block) -> int:
    """Приоритет типа блока: TABLE > IMAGE > TEXT"""
    if block.block_type == BlockType.TABLE:
        return 3
    if block.block_type == BlockType.IMAGE:
        return 2
    return 1


def _select_best_block(block1: Block, block2: Block) -> Block:
    """
    Выбрать лучший блок:
    1. TEXT vs IMAGE → TEXT (Surya точнее определяет текст)
    2. TABLE > всё остальное
    3. При равном типе — больший по площади
    """
    t1, t2 = block1.block_type, block2.block_type
    
    # TEXT vs IMAGE → TEXT побеждает
    if t1 == BlockType.TEXT and t2 == BlockType.IMAGE:
        return block1
    if t2 == BlockType.TEXT and t1 == BlockType.IMAGE:
        return block2
    
    # TABLE побеждает всё
    if t1 == BlockType.TABLE and t2 != BlockType.TABLE:
        return block1
    if t2 == BlockType.TABLE and t1 != BlockType.TABLE:
        return block2
    
    # Равный тип — берём больший
    return block1 if _get_block_area(block1) >= _get_block_area(block2) else block2


def _has_overlap(coords1: tuple, coords2: tuple) -> bool:
    """Проверка пересечения двух bbox"""
    return not (coords1[2] <= coords2[0] or coords2[2] <= coords1[0] or
                coords1[3] <= coords2[1] or coords2[3] <= coords1[1])


def merge_surya_paddle_blocks(surya_blocks: List[Block], paddle_blocks: List[Block], 
                               iou_threshold: float = 0.3) -> List[Block]:
    """
    Совмещение блоков Surya и Paddle без наложений.
    
    Правила:
    1. Блоки не накладываются
    2. Крупный блок побеждает мелкий
    3. Таблица > Картинка > Текст
    """
    all_blocks = surya_blocks + paddle_blocks
    
    # Сортируем: сначала по приоритету типа (desc), потом по площади (desc)
    all_blocks.sort(key=lambda b: (_get_block_priority(b), _get_block_area(b)), reverse=True)
    
    merged = []
    
    for block in all_blocks:
        dominated = False
        blocks_to_remove = []
        
        for i, existing in enumerate(merged):
            if not _has_overlap(block.coords_px, existing.coords_px):
                continue
            
            # Есть пересечение — выбираем лучший
            best = _select_best_block(block, existing)
            
            if best.id == existing.id:
                # Существующий лучше — пропускаем новый
                dominated = True
                break
            else:
                # Новый лучше — удаляем существующий
                blocks_to_remove.append(i)
        
        # Удаляем побеждённые блоки
        for i in reversed(blocks_to_remove):
            merged.pop(i)
        
        if not dominated:
            merged.append(block)
    
    logger.info(f"Merged: Surya={len(surya_blocks)}, Paddle={len(paddle_blocks)} -> {len(merged)} blocks")
    return merged


def segment_merged(pdf_path: str, pages: List[Page], 
                   page_images: Optional[dict] = None,
                   page_range: Optional[List[int]] = None,
                   category: str = "") -> Optional[List[Page]]:
    """
    Совмещённая разметка: Surya + Paddle с выбором лучших блоков.
    """
    temp_pdf_path = None
    target_pdf_path = pdf_path
    
    original_doc = fitz.open(pdf_path)
    pdf_page_dimensions = {}
    
    try:
        for page_idx in range(len(original_doc)):
            page = original_doc[page_idx]
            pdf_page_dimensions[page_idx] = (page.rect.width, page.rect.height)
        
        if page_range is not None:
            try:
                new_doc = fitz.open()
                new_doc.insert_pdf(original_doc, from_page=page_range[0], to_page=page_range[-1])
                
                fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
                os.close(fd)
                new_doc.save(temp_pdf_path, deflate=False, garbage=0, clean=False)
                new_doc.close()
                
                target_pdf_path = temp_pdf_path
            except Exception as e:
                logger.error(f"Ошибка создания временного PDF: {e}")
                if temp_pdf_path and os.path.exists(temp_pdf_path):
                    os.unlink(temp_pdf_path)
                raise
            finally:
                original_doc.close()
        else:
            original_doc.close()
        
        with open(target_pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        
        result = segment_pdf_layout(pdf_bytes)
        
        if not isinstance(result, dict) or 'pages' not in result:
            raise ValueError("API вернул некорректный формат данных")
        
        api_pages = result['pages']
        logger.info(f"Merged API: получено {len(api_pages)} страниц")
        
        for i, page_data in enumerate(api_pages):
            if page_range is not None:
                if i >= len(page_range):
                    break
                real_page_idx = page_range[i]
            else:
                real_page_idx = i
            
            if real_page_idx >= len(pages):
                continue
            
            page = pages[real_page_idx]
            
            if page_images and real_page_idx in page_images:
                real_img = page_images[real_page_idx]
                page_width = real_img.width
                page_height = real_img.height
            else:
                page_width = page.width
                page_height = page.height
            
            # Получаем блоки от обоих движков
            surya_blocks = _extract_blocks_from_surya_page(
                page_data, real_page_idx, page_width, page_height, category
            )
            paddle_blocks = _extract_blocks_from_paddle_raw(
                page_data, real_page_idx, page_width, page_height, category
            )
            
            # Совмещаем и выбираем лучшие
            merged_blocks = merge_surya_paddle_blocks(surya_blocks, paddle_blocks)
            
            # Фильтруем пересечения с существующими
            added_count = 0
            for new_block in merged_blocks:
                if not _is_overlapping_with_existing(new_block, page.blocks):
                    page.blocks.append(new_block)
                    added_count += 1
            
            logger.info(f"Страница {real_page_idx}: добавлено {added_count} merged блоков")
        
        return pages
        
    except Exception as e:
        logger.error(f"Ошибка merged сегментации: {e}", exc_info=True)
        raise
    finally:
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            try:
                os.unlink(temp_pdf_path)
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл: {e}")

