"""
Batch OCR с объединением блоков для экономии токенов.

Стратегия:
- TEXT/TABLE блоки объединяются вертикально в полосы до 9000px
- IMAGE блоки отправляются отдельно
- Результаты парсятся по маркерам [N] и вставляются в нужные блоки
"""

import logging
import base64
import io
import re
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass, field
from PIL import Image

from rd_core.models import Block, BlockType

logger = logging.getLogger(__name__)

MAX_STRIP_HEIGHT = 9000  # Максимальная высота объединённой полосы
MAX_IMAGE_SIZE = 1500    # Максимальный размер стороны для base64


@dataclass
class BatchStrip:
    """Полоса объединённых блоков"""
    blocks: List[Block] = field(default_factory=list)
    crops: List[Image.Image] = field(default_factory=list)
    total_height: int = 0
    max_width: int = 0


def image_to_base64(image: Image.Image, max_size: int = MAX_IMAGE_SIZE, quality: int = 85) -> str:
    """Конвертация в base64 с оптимизацией размера"""
    if image.width > max_size or image.height > max_size:
        ratio = min(max_size / image.width, max_size / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        image = image.resize(new_size, Image.LANCZOS)
    
    buffer = io.BytesIO()
    if image.mode in ('RGBA', 'LA'):
        image.save(buffer, format='PNG', optimize=True)
    else:
        image = image.convert('RGB')
        image.save(buffer, format='JPEG', quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def merge_crops_vertically(crops: List[Image.Image], gap: int = 20) -> Image.Image:
    """
    Объединить кропы вертикально с разделителем.
    
    Args:
        crops: список изображений
        gap: отступ между блоками
    
    Returns:
        Объединённое изображение
    """
    if not crops:
        raise ValueError("Список кропов пуст")
    
    if len(crops) == 1:
        return crops[0]
    
    max_width = max(c.width for c in crops)
    total_height = sum(c.height for c in crops) + gap * (len(crops) - 1)
    
    # Создаём белый холст
    merged = Image.new('RGB', (max_width, total_height), (255, 255, 255))
    
    y_offset = 0
    for crop in crops:
        # Центрируем по горизонтали
        x_offset = (max_width - crop.width) // 2
        
        if crop.mode in ('RGBA', 'LA'):
            crop = crop.convert('RGB')
        
        merged.paste(crop, (x_offset, y_offset))
        y_offset += crop.height + gap
    
    return merged


def group_blocks_into_strips(
    blocks_with_crops: List[Tuple[Block, Image.Image]]
) -> Tuple[List[BatchStrip], List[Tuple[Block, Image.Image]]]:
    """
    Группировка блоков в полосы для batch OCR.
    
    Args:
        blocks_with_crops: список (block, crop) отсортированный по порядку в документе
    
    Returns:
        (strips, image_blocks) - полосы TEXT/TABLE и отдельные IMAGE блоки
    """
    strips: List[BatchStrip] = []
    image_blocks: List[Tuple[Block, Image.Image]] = []
    
    current_strip = BatchStrip()
    
    for block, crop in blocks_with_crops:
        if block.block_type == BlockType.IMAGE:
            # IMAGE блоки идут отдельно
            # Сначала закрываем текущую полосу если есть
            if current_strip.blocks:
                strips.append(current_strip)
                current_strip = BatchStrip()
            
            image_blocks.append((block, crop))
            continue
        
        # TEXT или TABLE
        crop_height = crop.height
        crop_width = crop.width
        
        # Проверяем, влезет ли в текущую полосу
        if current_strip.total_height + crop_height > MAX_STRIP_HEIGHT and current_strip.blocks:
            # Закрываем текущую полосу, начинаем новую
            strips.append(current_strip)
            current_strip = BatchStrip()
        
        current_strip.blocks.append(block)
        current_strip.crops.append(crop)
        current_strip.total_height += crop_height + 20  # +gap
        current_strip.max_width = max(current_strip.max_width, crop_width)
    
    # Закрываем последнюю полосу
    if current_strip.blocks:
        strips.append(current_strip)
    
    logger.info(f"Сгруппировано: {len(strips)} полос TEXT/TABLE, {len(image_blocks)} IMAGE блоков")
    return strips, image_blocks


def run_batch_ocr(
    blocks: List[Block],
    block_crops: Dict[str, Image.Image],
    ocr_backend,
    prompt_loader: Optional[Callable] = None,
    on_progress: Optional[Callable[[int, int], None]] = None
) -> None:
    """
    Batch OCR с объединением блоков.
    
    Args:
        blocks: список блоков
        block_crops: словарь block_id -> PIL Image
        ocr_backend: OCR движок с методом recognize()
        prompt_loader: функция загрузки промптов
        on_progress: callback прогресса
    """
    # Сортируем блоки по странице и y-координате
    sorted_blocks = sorted(blocks, key=lambda b: (b.page_index, b.coords_px[1]))
    
    # Собираем блоки с кропами в правильном порядке
    blocks_with_crops = []
    for block in sorted_blocks:
        crop = block_crops.get(block.id)
        if crop:
            blocks_with_crops.append((block, crop))
    
    if not blocks_with_crops:
        logger.warning("Нет блоков для OCR")
        return
    
    total = len(blocks_with_crops)
    processed = 0
    
    # Группируем
    strips, image_blocks = group_blocks_into_strips(blocks_with_crops)
    
    logger.info(f"Batch OCR: {total} блоков, {len(strips)} полос TEXT/TABLE, {len(image_blocks)} IMAGE")
    
    # Обрабатываем полосы TEXT/TABLE
    for strip_idx, strip in enumerate(strips):
        try:
            logger.info(f"Обработка полосы {strip_idx + 1}/{len(strips)}: {len(strip.blocks)} блоков")
            results = _process_strip(strip, ocr_backend, prompt_loader)
            
            # Записываем результаты в блоки (напрямую, т.к. strip.blocks - те же объекты)
            for i, block in enumerate(strip.blocks):
                if block.id in results:
                    block.ocr_text = results[block.id]
                    logger.debug(f"Блок {block.id}: OCR текст {len(block.ocr_text)} символов")
                processed += 1
                if on_progress:
                    on_progress(processed, total)
                    
        except Exception as e:
            logger.error(f"Ошибка обработки полосы {strip_idx + 1}: {e}", exc_info=True)
            # Fallback: обрабатываем блоки по одному
            for block, crop in zip(strip.blocks, strip.crops):
                try:
                    prompt_data = _get_prompt_for_block(block, prompt_loader)
                    text = ocr_backend.recognize(crop, prompt=prompt_data)
                    block.ocr_text = text
                except Exception as e2:
                    block.ocr_text = f"[Ошибка: {e2}]"
                processed += 1
                if on_progress:
                    on_progress(processed, total)
    
    # Обрабатываем IMAGE блоки по одному
    for img_idx, (block, crop) in enumerate(image_blocks):
        try:
            logger.info(f"Обработка IMAGE блока {img_idx + 1}/{len(image_blocks)}: {block.id}")
            prompt_data = _get_prompt_for_block(block, prompt_loader)
            text = ocr_backend.recognize(crop, prompt=prompt_data)
            block.ocr_text = text
            logger.debug(f"IMAGE блок {block.id}: OCR текст {len(text)} символов")
        except Exception as e:
            logger.error(f"Ошибка OCR для IMAGE блока {block.id}: {e}")
            block.ocr_text = f"[Ошибка: {e}]"
        processed += 1
        if on_progress:
            on_progress(processed, total)
    
    logger.info(f"Batch OCR завершён: {processed} блоков обработано")


def _process_strip(
    strip: BatchStrip,
    ocr_backend,
    prompt_loader: Optional[Callable]
) -> Dict[str, str]:
    """
    Обработка одной полосы объединённых блоков.
    
    Returns:
        Dict[block_id -> ocr_text]
    """
    if len(strip.blocks) == 1:
        # Один блок - обычный запрос
        block = strip.blocks[0]
        crop = strip.crops[0]
        prompt_data = _get_prompt_for_block(block, prompt_loader)
        text = ocr_backend.recognize(crop, prompt=prompt_data)
        return {block.id: text}
    
    # Несколько блоков - объединяем и парсим
    merged_image = merge_crops_vertically(strip.crops)
    
    # Формируем промпт для batch
    prompt_data = _build_batch_prompt(strip.blocks, prompt_loader)
    
    # Распознаём
    response_text = ocr_backend.recognize(merged_image, prompt=prompt_data)
    
    # Парсим результаты
    return _parse_batch_response(strip.blocks, response_text)


def _get_prompt_for_block(block: Block, prompt_loader: Optional[Callable]) -> Optional[dict]:
    """Получить промпт для блока"""
    if not prompt_loader:
        return None

    type_map = {
        BlockType.TEXT: "text",
        BlockType.TABLE: "table",
        BlockType.IMAGE: "image",
    }
    type_key = type_map.get(block.block_type, "text")
    return prompt_loader(type_key)


def _build_batch_prompt(blocks: List[Block], prompt_loader: Optional[Callable]) -> dict:
    """
    Построить промпт для batch запроса.
    
    Формат ответа: [1] результат первого ... [N] результат N-го
    """
    # Базовый промпт
    base_prompt = _get_prompt_for_block(blocks[0], prompt_loader)
    
    system = base_prompt.get("system", "") if base_prompt else ""
    user = base_prompt.get("user", "Распознай содержимое.") if base_prompt else "Распознай содержимое."
    
    # Добавляем инструкцию по формату
    batch_instruction = (
        f"\n\nНа изображении {len(blocks)} блоков, расположенных вертикально (сверху вниз).\n"
        f"Распознай каждый блок ОТДЕЛЬНО.\n"
        f"Формат ответа:\n"
    )
    for i in range(1, len(blocks) + 1):
        batch_instruction += f"[{i}] <результат блока {i}>\n"
    
    batch_instruction += "\nНе объединяй блоки. Каждый блок — отдельный фрагмент документа."
    
    return {
        "system": system,
        "user": user + batch_instruction
    }


def _parse_batch_response(blocks: List[Block], response_text: str) -> Dict[str, str]:
    """
    Парсинг ответа с маркерами [1], [2], ...
    
    Returns:
        Dict[block_id -> text]
    """
    results = {}
    
    if len(blocks) == 1:
        results[blocks[0].id] = response_text.strip()
        return results
    
    # Разбиваем по маркерам [N]
    # Паттерн: [число] в начале строки или после переноса
    parts = re.split(r'\n?\[(\d+)\]\s*', response_text)
    
    # parts = ['преамбула', '1', 'текст1', '2', 'текст2', ...]
    parsed = {}
    for i in range(1, len(parts) - 1, 2):
        try:
            idx = int(parts[i]) - 1  # 1-based -> 0-based
            text = parts[i + 1].strip()
            if 0 <= idx < len(blocks):
                parsed[idx] = text
        except (ValueError, IndexError):
            continue
    
    # Присваиваем результаты
    for i, block in enumerate(blocks):
        if i in parsed:
            results[block.id] = parsed[i]
        else:
            # Fallback: если не распарсилось, весь текст первому блоку
            if i == 0 and not parsed:
                results[block.id] = response_text.strip()
            else:
                results[block.id] = "[Ошибка парсинга]"
    
    return results


def estimate_savings(total_blocks: int, strips_count: int, images_count: int) -> dict:
    """
    Оценка экономии токенов.
    
    Примерный расчёт:
    - System prompt: ~100 токенов
    - Request overhead: ~50 токенов
    """
    OVERHEAD_PER_REQUEST = 150
    
    baseline_requests = total_blocks
    optimized_requests = strips_count + images_count
    
    saved_requests = baseline_requests - optimized_requests
    saved_tokens = saved_requests * OVERHEAD_PER_REQUEST
    
    savings_percent = (saved_requests / baseline_requests * 100) if baseline_requests > 0 else 0
    
    return {
        "baseline_requests": baseline_requests,
        "optimized_requests": optimized_requests,
        "saved_requests": saved_requests,
        "saved_tokens": saved_tokens,
        "savings_percent": round(savings_percent, 1)
    }

