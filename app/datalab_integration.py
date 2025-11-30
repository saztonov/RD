"""
Интеграция с Datalab API для автоматической разметки PDF
https://documentation.datalab.to/api-reference/layout
"""

from pathlib import Path
from typing import List, Optional
import logging
import requests
import os
import json

from app.models import Block, BlockType, BlockSource, Page

logger = logging.getLogger(__name__)

DATALAB_API_URL = "https://www.datalab.to/api/v1"


class DatalabSegmentation:
    """Разметка PDF с использованием Datalab API"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: API ключ Datalab (если None, читается из переменной окружения DATALAB_API_KEY)
        """
        self.api_key = api_key or os.getenv("DATALAB_API_KEY")
        if not self.api_key:
            raise ValueError("Datalab API key не найден. Установите переменную окружения DATALAB_API_KEY или передайте api_key")
    
    def segment_pdf(self, pdf_path: str, pages: List[Page], 
                    page_images: Optional[dict] = None, page_range: Optional[List[int]] = None, category: str = "") -> List[Page]:
        """
        Разметка PDF с помощью Datalab Layout API
        
        Args:
            pdf_path: путь к PDF файлу
            pages: список страниц Document
            page_images: словарь {page_num: PIL.Image} (не используется для детекции)
            page_range: список индексов страниц для обработки (если None, обрабатываются все)
            category: категория для создаваемых блоков
        
        Returns:
            Обновленный список страниц с блоками от Datalab
        """
        try:
            # Если указан диапазон, обрабатываем только его
            pages_to_process = page_range if page_range is not None else list(range(len(pages)))
            
            logger.info(f"Запуск Datalab Layout API для {pdf_path}, страниц: {len(pages_to_process)}")
            
            # Загружаем файл
            file_id = self._upload_file(pdf_path)
            logger.info(f"Файл загружен, file_id: {file_id}")
            
            # Запускаем Layout анализ
            result = self._run_layout(file_id)
            
            # Обрабатываем результаты
            if result and "pages" in result:
                for page_result in result["pages"]:
                    page_num = page_result.get("page", 0)
                    
                    # Проверяем, входит ли страница в обрабатываемый диапазон
                    if page_num not in pages_to_process:
                        continue
                    
                    if page_num >= len(pages):
                        continue
                    
                    page = pages[page_num]
                    
                    # Извлекаем блоки
                    blocks_data = page_result.get("layout", [])
                    new_blocks = self._extract_blocks_from_layout(
                        blocks_data, page_num, page.width, page.height, category
                    )
                    
                    # Добавляем блоки, избегая дубликатов
                    added_count = 0
                    for new_block in new_blocks:
                        if not self._is_overlapping_with_existing(new_block, page.blocks):
                            page.blocks.append(new_block)
                            added_count += 1
                    
                    if added_count > 0:
                        logger.info(f"Страница {page_num}: добавлено {added_count} блоков (найдено {len(new_blocks)})")
            
            return pages
            
        except Exception as e:
            logger.error(f"Ошибка Datalab API: {e}", exc_info=True)
            raise
    
    def _upload_file(self, pdf_path: str) -> str:
        """Загружает PDF файл в Datalab и возвращает file_id"""
        
        # Шаг 1: Запросить upload URL
        upload_url_response = requests.post(
            f"{DATALAB_API_URL}/files/request-upload-url",
            headers={"X-API-Key": self.api_key},
            json={"filename": Path(pdf_path).name}
        )
        upload_url_response.raise_for_status()
        
        upload_data = upload_url_response.json()
        upload_url = upload_data["upload_url"]
        file_id = upload_data["file_id"]
        
        # Шаг 2: Загрузить файл по upload_url
        with open(pdf_path, "rb") as f:
            upload_response = requests.put(upload_url, data=f)
            upload_response.raise_for_status()
        
        # Шаг 3: Подтвердить загрузку
        confirm_response = requests.post(
            f"{DATALAB_API_URL}/files/{file_id}/confirm-upload",
            headers={"X-API-Key": self.api_key}
        )
        confirm_response.raise_for_status()
        
        return file_id
    
    def _run_layout(self, file_id: str) -> dict:
        """Запускает Layout анализ и возвращает результат"""
        
        # Запустить layout задачу
        response = requests.post(
            f"{DATALAB_API_URL}/layout",
            headers={"X-API-Key": self.api_key},
            json={"file_id": file_id}
        )
        response.raise_for_status()
        
        task_data = response.json()
        task_id = task_data.get("task_id")
        
        if not task_id:
            raise ValueError("Не получен task_id от Datalab API")
        
        logger.info(f"Layout задача запущена, task_id: {task_id}")
        
        # Опрашиваем статус до завершения
        import time
        max_attempts = 60
        for attempt in range(max_attempts):
            status_response = requests.get(
                f"{DATALAB_API_URL}/layout/{task_id}/status",
                headers={"X-API-Key": self.api_key}
            )
            status_response.raise_for_status()
            
            status_data = status_response.json()
            status = status_data.get("status")
            
            if status == "completed":
                result = status_data.get("result")
                return result
            elif status == "failed":
                error = status_data.get("error", "Unknown error")
                raise ValueError(f"Layout задача завершилась с ошибкой: {error}")
            
            time.sleep(2)
        
        raise TimeoutError("Layout задача не завершилась за отведенное время")
    
    def _extract_blocks_from_layout(self, blocks_data: List[dict], page_idx: int,
                                     page_width: float, page_height: float, category: str = "") -> List[Block]:
        """Извлечение блоков из результата Layout API"""
        blocks = []
        
        for block_data in blocks_data:
            try:
                bbox = block_data.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                
                # bbox в формате [x1, y1, x2, y2], нормализованные [0, 1]
                x1 = int(bbox[0] * page_width)
                y1 = int(bbox[1] * page_height)
                x2 = int(bbox[2] * page_width)
                y2 = int(bbox[3] * page_height)
                
                # Определяем тип блока
                label = block_data.get("label", "").lower()
                block_type = self._detect_block_type(label)
                
                block = Block.create(
                    page_index=page_idx,
                    coords_px=(x1, y1, x2, y2),
                    page_width=page_width,
                    page_height=page_height,
                    category=category,
                    block_type=block_type,
                    source=BlockSource.AUTO
                )
                
                blocks.append(block)
                
            except Exception as e:
                logger.warning(f"Ошибка обработки блока: {e}")
                continue
        
        return blocks
    
    def _detect_block_type(self, label: str) -> BlockType:
        """Определение типа блока из label"""
        label = label.lower()
        
        if 'table' in label:
            return BlockType.TABLE
        elif 'figure' in label or 'image' in label or 'picture' in label:
            return BlockType.IMAGE
        else:
            return BlockType.TEXT
    
    def _is_overlapping_with_existing(self, new_block: Block, existing_blocks: List[Block], threshold: float = 0.3) -> bool:
        """Проверка пересечения нового блока с существующими"""
        new_coords = new_block.coords_px
        
        for existing in existing_blocks:
            ex_coords = existing.coords_px
            
            x_left = max(new_coords[0], ex_coords[0])
            y_top = max(new_coords[1], ex_coords[1])
            x_right = min(new_coords[2], ex_coords[2])
            y_bottom = min(new_coords[3], ex_coords[3])
            
            if x_right < x_left or y_bottom < y_top:
                continue
            
            intersection_area = (x_right - x_left) * (y_bottom - y_top)
            new_block_area = (new_coords[2] - new_coords[0]) * (new_coords[3] - new_coords[1])
            
            if new_block_area <= 0:
                continue
            
            if (intersection_area / new_block_area) > threshold:
                return True
        
        return False


def segment_with_datalab(pdf_path: str, pages: List[Page],
                         page_images: Optional[dict] = None, page_range: Optional[List[int]] = None,
                         category: str = "", api_key: Optional[str] = None) -> Optional[List[Page]]:
    """
    Функция-обертка для разметки PDF через Datalab API
    
    Args:
        pdf_path: путь к PDF
        pages: список страниц
        page_images: словарь изображений страниц (опционально)
        page_range: список индексов страниц для обработки
        category: категория для создаваемых блоков
        api_key: API ключ Datalab (опционально)
    
    Returns:
        Обновленный список страниц или None при ошибке
    """
    try:
        segmenter = DatalabSegmentation(api_key=api_key)
        return segmenter.segment_pdf(pdf_path, pages, page_images, page_range, category)
    except Exception as e:
        logger.error(f"Ошибка разметки Datalab: {e}")
        return None

