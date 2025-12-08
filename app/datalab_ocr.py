"""
Datalab OCR - распознавание текста/таблиц через Datalab Marker API
Экономия бюджета: склейка блоков в одно изображение
"""

import logging
import time
import io
import os
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from PIL import Image
import requests

logger = logging.getLogger(__name__)

# Константы склейки
TARGET_WIDTH = 2500       # Ширина результата
BLOCK_PADDING = 100       # Отступ между блоками
MAX_HEIGHT = 10000        # Максимальная высота батча
MAX_FILE_SIZE_MB = 200    # Лимит размера файла


class DatalabOCRClient:
    """Клиент для Datalab Marker API"""
    
    API_URL = "https://www.datalab.to/api/v1/marker"
    POLL_INTERVAL = 2      # секунд
    MAX_POLL_ATTEMPTS = 60 # 2 минуты максимум
    
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("DATALAB_API_KEY не указан")
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}
    
    def recognize(self, image_path: str, block_prompt: str = None) -> str:
        """
        Отправить изображение на распознавание
        
        Args:
            image_path: путь к изображению
            block_prompt: промпт для коррекции блока (block_correction_prompt)
        
        Returns:
            Markdown с распознанным текстом
        """
        logger.info(f"Datalab OCR: отправка {image_path}")
        
        # Отправка запроса
        with open(image_path, 'rb') as f:
            files = {'file': (os.path.basename(image_path), f, 'image/png')}
            # Параметры оптимизированы для строительных чертежей
            # https://documentation.datalab.to/api-reference/marker
            data = {
                'mode': 'accurate',            # Максимальная точность
                'force_ocr': 'true',           # Игнорировать битый текстовый слой PDF
                'paginate': 'false',           # Сплошной текст без разрывов
                'use_llm': 'true',             # LLM для коррекции артефактов и таблиц
                'output_format': 'markdown',
                'disable_image_extraction': 'true'
            }
            
            # Добавляем промпт для коррекции если указан
            if block_prompt:
                data['block_correction_prompt'] = block_prompt
            
            response = requests.post(
                self.API_URL,
                headers=self.headers,
                files=files,
                data=data,
                timeout=120
            )
        
        if response.status_code != 200:
            logger.error(f"Datalab API error: {response.status_code} - {response.text}")
            raise Exception(f"Datalab API error: {response.status_code}")
        
        result = response.json()
        
        if not result.get('success'):
            error = result.get('error', 'Unknown error')
            logger.error(f"Datalab API failed: {error}")
            raise Exception(f"Datalab API failed: {error}")
        
        # Получаем URL для проверки статуса
        request_check_url = result.get('request_check_url')
        if not request_check_url:
            # Синхронный ответ (маловероятно, но возможно)
            if 'markdown' in result:
                return result['markdown']
            raise Exception("Нет request_check_url в ответе")
        
        # Поллинг результата
        return self._poll_result(request_check_url)
    
    def _poll_result(self, check_url: str) -> str:
        """Ожидание и получение результата"""
        logger.info(f"Datalab: ожидание результата...")
        
        for attempt in range(self.MAX_POLL_ATTEMPTS):
            time.sleep(self.POLL_INTERVAL)
            
            try:
                response = requests.get(check_url, headers=self.headers, timeout=30)
                result = response.json()
                
                status = result.get('status', '')
                
                if status == 'complete':
                    logger.info("Datalab: обработка завершена")
                    markdown = result.get('markdown') or ''
                    return markdown
                
                elif status == 'failed':
                    error = result.get('error', 'Unknown error')
                    logger.error(f"Datalab processing failed: {error}")
                    raise Exception(f"Datalab failed: {error}")
                
                # Продолжаем ждать
                logger.debug(f"Datalab status: {status}, attempt {attempt + 1}")
                
            except requests.RequestException as e:
                logger.warning(f"Poll request failed: {e}")
                # Продолжаем попытки
        
        raise Exception("Datalab: превышено время ожидания")


def resize_to_width(image: Image.Image, target_width: int = TARGET_WIDTH) -> Image.Image:
    """Масштабировать изображение до заданной ширины, сохраняя пропорции"""
    if image.width == target_width:
        return image
    
    ratio = target_width / image.width
    new_height = int(image.height * ratio)
    return image.resize((target_width, new_height), Image.LANCZOS)


def concatenate_blocks(
    block_images: List[Image.Image],
    padding: int = BLOCK_PADDING,
    max_height: int = MAX_HEIGHT,
    target_width: int = TARGET_WIDTH
) -> List[Image.Image]:
    """
    Склеить блоки в вертикальные ленты
    
    Args:
        block_images: список PIL изображений блоков
        padding: отступ между блоками
        max_height: максимальная высота одного батча
        target_width: целевая ширина
    
    Returns:
        Список склеенных изображений (батчей)
    """
    if not block_images:
        return []
    
    # Ресайзим все блоки
    resized = [resize_to_width(img, target_width) for img in block_images]
    
    batches = []
    current_batch = []
    current_height = 0
    
    for img in resized:
        # Проверяем, поместится ли блок в текущий батч
        needed_height = img.height + (padding if current_batch else 0)
        
        if current_height + needed_height > max_height and current_batch:
            # Сохраняем текущий батч, начинаем новый
            batches.append(_create_batch_image(current_batch, padding, target_width))
            current_batch = [img]
            current_height = img.height
        else:
            current_batch.append(img)
            current_height += needed_height
    
    # Последний батч
    if current_batch:
        batches.append(_create_batch_image(current_batch, padding, target_width))
    
    return batches


def _create_batch_image(images: List[Image.Image], padding: int, width: int) -> Image.Image:
    """Создать одно изображение из списка блоков"""
    total_height = sum(img.height for img in images) + padding * (len(images) - 1)
    
    # Белый холст
    canvas = Image.new('RGB', (width, total_height), (255, 255, 255))
    
    y_offset = 0
    for img in images:
        # Конвертируем в RGB если нужно
        if img.mode != 'RGB':
            img = img.convert('RGB')
        canvas.paste(img, (0, y_offset))
        y_offset += img.height + padding
    
    return canvas


def save_optimized_image(image: Image.Image, output_path: str, max_size_mb: int = MAX_FILE_SIZE_MB) -> str:
    """
    Сохранить изображение с оптимизацией размера
    
    Returns:
        Путь к сохраненному файлу
    """
    path = Path(output_path)
    
    # Сначала пробуем PNG
    image.save(output_path, format='PNG', optimize=True)
    
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    
    if size_mb > max_size_mb:
        # Переключаемся на JPEG с понижением качества
        jpeg_path = path.with_suffix('.jpg')
        quality = 95
        
        while quality >= 60:
            image.save(str(jpeg_path), format='JPEG', quality=quality, optimize=True)
            size_mb = os.path.getsize(str(jpeg_path)) / (1024 * 1024)
            
            if size_mb <= max_size_mb:
                # Удаляем PNG если был создан
                if path.exists() and path.suffix == '.png':
                    path.unlink()
                return str(jpeg_path)
            
            quality -= 10
        
        raise ValueError(f"Не удалось уменьшить файл до {max_size_mb}MB")
    
    return output_path


def process_blocks_with_datalab(
    block_images: List[Image.Image],
    api_key: str,
    temp_dir: str,
    progress_callback=None
) -> List[str]:
    """
    Обработать блоки через Datalab API с оптимизацией
    
    Args:
        block_images: список PIL изображений блоков
        api_key: ключ API Datalab
        temp_dir: директория для временных файлов
        progress_callback: функция обратного вызова (current, total, message)
    
    Returns:
        Список markdown строк для каждого батча
    """
    if not block_images:
        return []
    
    client = DatalabOCRClient(api_key)
    temp_path = Path(temp_dir)
    temp_path.mkdir(parents=True, exist_ok=True)
    
    # Склеиваем блоки в батчи
    if progress_callback:
        progress_callback(0, 100, "Склейка блоков...")
    
    batches = concatenate_blocks(block_images)
    total_batches = len(batches)
    
    logger.info(f"Datalab: {len(block_images)} блоков → {total_batches} батчей")
    
    results = []
    
    for i, batch_image in enumerate(batches):
        if progress_callback:
            progress_callback(
                int((i / total_batches) * 100),
                100,
                f"Обработка батча {i + 1}/{total_batches}..."
            )
        
        # Сохраняем батч
        batch_path = temp_path / f"batch_{i}.png"
        saved_path = save_optimized_image(batch_image, str(batch_path))
        
        try:
            # Отправляем на распознавание
            markdown = client.recognize(saved_path)
            results.append(markdown)
            
        except Exception as e:
            logger.error(f"Ошибка обработки батча {i}: {e}")
            results.append(f"[Ошибка распознавания батча {i + 1}: {e}]")
        
        finally:
            # Удаляем временный файл
            for p in [batch_path, batch_path.with_suffix('.jpg')]:
                if p.exists():
                    p.unlink()
    
    if progress_callback:
        progress_callback(100, 100, "Готово")
    
    return results


def run_datalab_ocr_for_blocks(
    blocks,
    page_images: Dict[int, Image.Image],
    api_key: str,
    temp_dir: str,
    progress_callback=None
) -> str:
    """
    Запустить Datalab OCR для списка блоков
    
    Args:
        blocks: список Block объектов
        page_images: словарь {page_num: PIL.Image}
        api_key: ключ API Datalab
        temp_dir: временная директория
        progress_callback: callback прогресса
    
    Returns:
        Объединенный markdown результат
    """
    # Извлекаем изображения блоков
    block_images = []
    block_info = []  # Для сопоставления результатов
    
    for block in blocks:
        page_num = block.page_number if hasattr(block, 'page_number') else 0
        
        if page_num not in page_images:
            continue
        
        page_img = page_images[page_num]
        x1, y1, x2, y2 = block.coords_px
        
        if x1 >= x2 or y1 >= y2:
            continue
        
        crop = page_img.crop((x1, y1, x2, y2))
        block_images.append(crop)
        block_info.append(block)
    
    if not block_images:
        return ""
    
    # Обрабатываем через Datalab
    results = process_blocks_with_datalab(
        block_images,
        api_key,
        temp_dir,
        progress_callback
    )
    
    # Объединяем результаты
    return "\n\n---\n\n".join(results)


class DatalabOCRBackend:
    """Backend для интеграции с существующей системой OCR"""
    
    def __init__(self, api_key: str):
        self.client = DatalabOCRClient(api_key)
        self._temp_counter = 0
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None) -> str:
        """
        Распознать одиночное изображение через Datalab
        Примечание: неэффективно для одиночных блоков, лучше использовать batch
        """
        import tempfile
        
        self._temp_counter += 1
        temp_path = Path(tempfile.gettempdir()) / f"datalab_single_{self._temp_counter}.png"
        
        try:
            # Ресайзим если нужно
            resized = resize_to_width(image, TARGET_WIDTH)
            saved_path = save_optimized_image(resized, str(temp_path))
            
            return self.client.recognize(saved_path)
            
        finally:
            for p in [temp_path, temp_path.with_suffix('.jpg')]:
                if p.exists():
                    p.unlink()

