"""
Оптимизированный Batch OCR с экономией токенов
- Группировка блоков по промпту
- Multi-image batching
- Сохранение контекста между запросами
"""

import logging
import base64
import io
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from PIL import Image
from app.models import Block, BlockType

logger = logging.getLogger(__name__)


@dataclass
class BatchItem:
    """Элемент батча"""
    block: Block
    crop: Image.Image
    page_num: int


@dataclass
class BatchGroup:
    """Группа блоков с одинаковым промптом"""
    prompt_key: str  # "category_X" или "type_text/table/image"
    prompt_text: str
    items: List[BatchItem] = field(default_factory=list)


def image_to_base64_optimized(image: Image.Image, max_size: int = 1200, quality: int = 85) -> str:
    """Оптимизированная конвертация: меньший размер = меньше токенов на изображение"""
    if image.width > max_size or image.height > max_size:
        ratio = min(max_size / image.width, max_size / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        image = image.resize(new_size, Image.LANCZOS)
    
    # JPEG меньше PNG для фото, PNG лучше для текста/схем
    buffer = io.BytesIO()
    if image.mode in ('RGBA', 'LA'):
        image.save(buffer, format='PNG', optimize=True)
    else:
        image = image.convert('RGB')
        image.save(buffer, format='JPEG', quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


class BatchOCREngine:
    """
    Движок batch OCR с оптимизацией токенов
    
    Стратегии экономии:
    1. Группировка по промпту → 1 system prompt на группу
    2. Multi-image в одном запросе → меньше overhead
    3. Контекст между группами → модель "помнит" предыдущее
    """
    
    MAX_IMAGES_PER_REQUEST = 4  # Оптимально для большинства VLM
    MAX_CONTEXT_TOKENS = 8000   # Резерв под контекст предыдущих результатов
    
    def __init__(self, api_client, model_name: str, use_context: bool = True):
        """
        Args:
            api_client: HTTP клиент (httpx или requests)
            model_name: Имя модели
            use_context: Сохранять контекст между группами
        """
        self.api_client = api_client
        self.model_name = model_name
        self.use_context = use_context
        self._context_summary = ""  # Краткое резюме предыдущих результатов
    
    def group_blocks_by_prompt(
        self, 
        blocks_with_crops: List[Tuple[Block, Image.Image, int]], 
        prompt_loader
    ) -> List[BatchGroup]:
        """
        Группировка СОСЕДНИХ блоков по промпту с сохранением порядка документа.
        
        Логика:
        - Группируем только последовательные блоки с одинаковым промптом
        - Сохраняем порядок блоков в документе
        - Batching работает для соседних блоков одного типа/категории
        
        Пример: [TEXT, TEXT, IMAGE, TEXT, TABLE, TABLE]
        Группы: [[TEXT, TEXT], [IMAGE], [TEXT], [TABLE, TABLE]]
        """
        groups: List[BatchGroup] = []
        current_group: Optional[BatchGroup] = None
        
        for block, crop, page_num in blocks_with_crops:
            # Определяем ключ и текст промпта
            prompt_key, prompt_text = self._get_prompt_key(block, prompt_loader)
            
            # Если тот же промпт что и у текущей группы - добавляем
            if current_group and current_group.prompt_key == prompt_key:
                current_group.items.append(BatchItem(block=block, crop=crop, page_num=page_num))
            else:
                # Новая группа
                current_group = BatchGroup(
                    prompt_key=prompt_key,
                    prompt_text=prompt_text,
                    items=[BatchItem(block=block, crop=crop, page_num=page_num)]
                )
                groups.append(current_group)
        
        logger.info(f"Сгруппировано {len(blocks_with_crops)} блоков в {len(groups)} последовательных групп")
        return groups
    
    def _get_prompt_key(self, block: Block, prompt_loader) -> Tuple[str, str]:
        """Получить ключ и текст промпта для блока"""
        # Приоритет 1: категория
        if block.category and block.category.strip():
            cat_key = f"category_{block.category.strip()}"
            prompt_text = prompt_loader(cat_key) if prompt_loader else None
            if prompt_text:
                return cat_key, prompt_text
        
        # Приоритет 2: тип блока
        type_map = {
            BlockType.IMAGE: "image",
            BlockType.TABLE: "table",
            BlockType.TEXT: "text",
        }
        type_key = type_map.get(block.block_type, "text")
        prompt_text = prompt_loader(type_key) if prompt_loader else self._default_prompt(block.block_type)
        return f"type_{type_key}", prompt_text or self._default_prompt(block.block_type)
    
    def _default_prompt(self, block_type: BlockType) -> str:
        """Минимальный fallback промпт (основные должны быть в R2)"""
        return "Распознай содержимое изображения."
    
    def process_group_batched(
        self, 
        group: BatchGroup, 
        api_url: str,
        on_progress: callable = None
    ) -> Dict[str, str]:
        """
        Обработка группы с batching изображений
        
        Returns:
            Dict[block_id -> ocr_text]
        """
        results = {}
        items = group.items
        
        # Разбиваем на батчи
        for batch_start in range(0, len(items), self.MAX_IMAGES_PER_REQUEST):
            batch = items[batch_start:batch_start + self.MAX_IMAGES_PER_REQUEST]
            
            try:
                batch_results = self._process_batch(batch, group.prompt_text, api_url)
                results.update(batch_results)
                
                if on_progress:
                    on_progress(batch_start + len(batch), len(items))
                    
            except Exception as e:
                logger.error(f"Ошибка batch OCR: {e}")
                # Fallback: обрабатываем по одному
                for item in batch:
                    try:
                        single_result = self._process_single(item, group.prompt_text, api_url)
                        results[item.block.id] = single_result
                    except Exception as e2:
                        results[item.block.id] = f"[Error: {e2}]"
        
        # Обновляем контекст для следующей группы
        if self.use_context and results:
            self._update_context_summary(group.prompt_key, results)
        
        return results
    
    def _process_batch(
        self, 
        batch: List[BatchItem], 
        prompt_text: str, 
        api_url: str
    ) -> Dict[str, str]:
        """Обработка батча изображений одним запросом"""
        
        # Формируем контент с несколькими изображениями
        content_parts = []
        
        # Добавляем контекст если есть
        if self.use_context and self._context_summary:
            content_parts.append({
                "type": "text",
                "text": f"[Контекст документа: {self._context_summary}]\n\n"
            })
        
        # Инструкция
        if len(batch) > 1:
            content_parts.append({
                "type": "text",
                "text": f"{prompt_text}\n\nОбработай {len(batch)} изображений. "
                        f"Ответ в формате:\n[1] результат первого\n[2] результат второго\n..."
            })
        else:
            content_parts.append({"type": "text", "text": prompt_text})
        
        # Добавляем изображения
        for i, item in enumerate(batch):
            img_b64 = image_to_base64_optimized(item.crop)
            format_hint = "png" if item.crop.mode in ('RGBA', 'LA') else "jpeg"
            
            if len(batch) > 1:
                content_parts.append({"type": "text", "text": f"\n[{i+1}] Страница {item.page_num + 1}:"})
            
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/{format_hint};base64,{img_b64}"}
            })
        
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert OCR system. Extract text/data accurately. Be concise."
                },
                {
                    "role": "user",
                    "content": content_parts
                }
            ],
            "max_tokens": 4096 * len(batch),  # Масштабируем под количество
            "temperature": 0.1,
        }
        
        response = self.api_client.post(api_url, json=payload, timeout=120 * len(batch))
        response.raise_for_status()
        
        result_text = response.json()["choices"][0]["message"]["content"].strip()
        
        # Парсим результат
        return self._parse_batch_response(batch, result_text)
    
    def _parse_batch_response(
        self, 
        batch: List[BatchItem], 
        response_text: str
    ) -> Dict[str, str]:
        """Парсинг ответа с несколькими результатами"""
        results = {}
        
        if len(batch) == 1:
            results[batch[0].block.id] = response_text
            return results
        
        # Разбиваем по маркерам [1], [2], ...
        import re
        parts = re.split(r'\n?\[(\d+)\]\s*', response_text)
        
        # parts = ['', '1', 'text1', '2', 'text2', ...]
        parsed = {}
        for i in range(1, len(parts) - 1, 2):
            idx = int(parts[i]) - 1
            text = parts[i + 1].strip()
            if 0 <= idx < len(batch):
                parsed[idx] = text
        
        # Присваиваем результаты
        for i, item in enumerate(batch):
            if i in parsed:
                results[item.block.id] = parsed[i]
            else:
                # Если парсинг не удался, берем весь текст для первого
                results[item.block.id] = response_text if i == 0 else "[Parsing error]"
        
        return results
    
    def _process_single(
        self, 
        item: BatchItem, 
        prompt_text: str, 
        api_url: str
    ) -> str:
        """Fallback: обработка одного изображения"""
        img_b64 = image_to_base64_optimized(item.crop)
        format_hint = "png" if item.crop.mode in ('RGBA', 'LA') else "jpeg"
        
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "Expert OCR. Be concise."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/{format_hint};base64,{img_b64}"}}
                    ]
                }
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }
        
        response = self.api_client.post(api_url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    
    def _update_context_summary(self, group_key: str, results: Dict[str, str]):
        """Обновление контекстного резюме - накапливается последовательно"""
        # Берем последний результат группы для контекста (он ближе к следующей группе)
        texts = [t for t in results.values() if t and not t.startswith("[Error")]
        if not texts:
            return
        
        # Берем последний результат (он идет перед следующей группой)
        last_text = texts[-1][:300] if texts else ""
        
        # Накапливаем контекст (скользящее окно ~500 символов)
        if self._context_summary:
            # Обрезаем старый контекст + добавляем новый
            self._context_summary = f"{self._context_summary[-200:]} ... {last_text}"
        else:
            self._context_summary = last_text


def estimate_token_savings(
    total_blocks: int, 
    groups_count: int, 
    avg_batch_size: float
) -> dict:
    """
    Оценка экономии токенов
    
    Примерный расчет:
    - System prompt: ~100 токенов (повторяется в каждом запросе)
    - Overhead запроса: ~50 токенов
    """
    SYSTEM_PROMPT_TOKENS = 100
    REQUEST_OVERHEAD = 50
    
    # Без оптимизации: каждый блок = отдельный запрос
    baseline_overhead = total_blocks * (SYSTEM_PROMPT_TOKENS + REQUEST_OVERHEAD)
    
    # С оптимизацией: группировка + batching
    num_requests = groups_count * (total_blocks / groups_count / avg_batch_size)
    optimized_overhead = num_requests * (SYSTEM_PROMPT_TOKENS + REQUEST_OVERHEAD)
    
    savings = baseline_overhead - optimized_overhead
    savings_percent = (savings / baseline_overhead * 100) if baseline_overhead > 0 else 0
    
    return {
        "baseline_requests": total_blocks,
        "optimized_requests": int(num_requests),
        "saved_tokens": int(savings),
        "savings_percent": round(savings_percent, 1)
    }

