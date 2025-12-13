"""
OCR обработка через API движки
Поддержка LocalVLM (через ngrok) и OpenRouter API
"""

import logging
import json
import base64
import io
from pathlib import Path
from typing import Protocol, List, Optional
from PIL import Image
from rd_core.models import Block, BlockType

logger = logging.getLogger(__name__)


def image_to_base64(image: Image.Image, max_size: int = 1500) -> str:
    """
    Конвертировать PIL Image в base64 с опциональным ресайзом
    
    Args:
        image: PIL изображение
        max_size: максимальный размер стороны
    
    Returns:
        Base64 строка
    """
    if image.width > max_size or image.height > max_size:
        ratio = min(max_size / image.width, max_size / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        image = image.resize(new_size, Image.LANCZOS)
    
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')




class OCRBackend(Protocol):
    """
    Интерфейс для OCR-движков
    """
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None) -> str:
        """
        Распознать текст на изображении
        
        Args:
            image: изображение для распознавания
            prompt: dict с ключами 'system' и 'user' (опционально)
        
        Returns:
            Распознанный текст
        """
        ...


class LocalVLMBackend:
    """OCR через ngrok endpoint (проксирует в LM Studio)"""
    
    DEFAULT_SYSTEM = "You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON or Markdown formats with 100% accuracy. Do not omit details. Do not hallucinate values."
    DEFAULT_USER = "Распознай содержимое изображения."
    
    def __init__(self, api_base: str = None, model_name: str = "qwen3-vl-32b-instruct"):
        self.model_name = model_name
        try:
            import httpx
            self.httpx = httpx
        except ImportError:
            raise ImportError("Требуется установить httpx: pip install httpx")
        logger.info(f"LocalVLM инициализирован (модель: {self.model_name})")
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None) -> str:
        """Распознать текст через ngrok endpoint"""
        try:
            from rd_core.config import get_lm_base_url
            
            # Извлекаем system и user из промта
            if prompt and isinstance(prompt, dict):
                system_prompt = prompt.get("system", "") or self.DEFAULT_SYSTEM
                user_prompt = prompt.get("user", "") or self.DEFAULT_USER
            else:
                system_prompt = self.DEFAULT_SYSTEM
                user_prompt = self.DEFAULT_USER
            
            img_base64 = image_to_base64(image)
            url = get_lm_base_url()
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                        ]
                    }
                ],
                "max_tokens": 16384,
                "temperature": 0.1,
                "top_p": 0.9,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0
            }
            
            with self.httpx.Client(timeout=600.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
            
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not text:
                logger.error(f"Пустой ответ от сервера: {result}")
                return "[Ошибка: пустой ответ от сервера]"
            
            logger.debug(f"VLM OCR: распознано {len(text)} символов")
            return text.strip()
            
        except self.httpx.ConnectError:
            logger.error("Не удалось подключиться к серверу")
            return "[Ошибка: сервер недоступен]"
        except self.httpx.TimeoutException:
            logger.error("Превышен таймаут")
            return "[Ошибка: таймаут сервера]"
        except Exception as e:
            logger.error(f"Ошибка VLM OCR: {e}", exc_info=True)
            return f"[Ошибка VLM OCR: {e}]"


class OpenRouterBackend:
    """OCR через OpenRouter API"""
    
    _providers_cache: dict = {}  # Кэш провайдеров по моделям
    
    DEFAULT_SYSTEM = "You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON or Markdown formats with 100% accuracy. Do not omit details. Do not hallucinate values."
    DEFAULT_USER = "Распознай содержимое изображения."
    
    def __init__(self, api_key: str, model_name: str = "qwen/qwen3-vl-30b-a3b-instruct"):
        self.api_key = api_key
        self.model_name = model_name
        self._provider_order: Optional[List[str]] = None
        try:
            import requests
            self.requests = requests
        except ImportError:
            raise ImportError("Требуется установить requests: pip install requests")
        logger.info(f"OpenRouter инициализирован (модель: {self.model_name})")
    
    def _fetch_cheapest_providers(self) -> Optional[List[str]]:
        """Получить список провайдеров отсортированных по цене (от дешевого к дорогому)"""
        if self.model_name in OpenRouterBackend._providers_cache:
            return OpenRouterBackend._providers_cache[self.model_name]
        
        try:
            response = self.requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30
            )
            if response.status_code != 200:
                logger.warning(f"Не удалось получить список моделей: {response.status_code}")
                return None
            
            models_data = response.json().get("data", [])
            
            # Ищем нужную модель
            model_info = None
            for m in models_data:
                if m.get("id") == self.model_name:
                    model_info = m
                    break
            
            if not model_info:
                logger.warning(f"Модель {self.model_name} не найдена в списке")
                return None
            
            # Получаем pricing по провайдерам
            pricing = model_info.get("endpoint", {}).get("pricing", {})
            if not pricing:
                # Fallback на старую структуру
                pricing = model_info.get("pricing", {})
            
            # Если pricing - словарь с провайдерами
            providers_pricing = []
            if isinstance(pricing, dict) and "providers" in pricing:
                for provider_id, pdata in pricing.get("providers", {}).items():
                    prompt_cost = float(pdata.get("prompt", 0) or 0)
                    completion_cost = float(pdata.get("completion", 0) or 0)
                    total = prompt_cost + completion_cost
                    providers_pricing.append((provider_id, total))
            elif isinstance(pricing, list):
                # pricing может быть списком объектов с provider_id
                for pdata in pricing:
                    provider_id = pdata.get("provider_id") or pdata.get("provider")
                    if provider_id:
                        prompt_cost = float(pdata.get("prompt", 0) or 0)
                        completion_cost = float(pdata.get("completion", 0) or 0)
                        total = prompt_cost + completion_cost
                        providers_pricing.append((provider_id, total))
            
            if not providers_pricing:
                logger.info("Pricing по провайдерам не найден, используется дефолт")
                return None
            
            # Сортируем по цене (от дешевого)
            providers_pricing.sort(key=lambda x: x[1])
            provider_order = [p[0] for p in providers_pricing]
            
            logger.info(f"Провайдеры для {self.model_name} (по цене): {provider_order}")
            OpenRouterBackend._providers_cache[self.model_name] = provider_order
            return provider_order
            
        except Exception as e:
            logger.warning(f"Ошибка получения провайдеров: {e}")
            return None
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None) -> str:
        """Распознать текст через OpenRouter API"""
        try:
            # Получаем порядок провайдеров (кэшируется)
            if self._provider_order is None:
                self._provider_order = self._fetch_cheapest_providers() or []
            
            image_b64 = image_to_base64(image)
            
            # Извлекаем system и user из промта
            if prompt and isinstance(prompt, dict):
                system_prompt = prompt.get("system", "") or self.DEFAULT_SYSTEM
                user_prompt = prompt.get("user", "") or self.DEFAULT_USER
            else:
                system_prompt = self.DEFAULT_SYSTEM
                user_prompt = self.DEFAULT_USER
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                        ]
                    }
                ],
                "max_tokens": 16384,
                "temperature": 0.1,
                "top_p": 0.9
            }
            
            # Добавляем provider.order если есть
            if self._provider_order:
                payload["provider"] = {"order": self._provider_order}
            
            response = self.requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=120
            )
            
            if response.status_code != 200:
                logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                return f"[Ошибка OpenRouter API: {response.status_code}]"
            
            result = response.json()
            text = result["choices"][0]["message"]["content"].strip()
            logger.debug(f"OpenRouter OCR: распознано {len(text)} символов")
            return text
            
        except self.requests.exceptions.Timeout:
            logger.error("OpenRouter OCR: превышен таймаут")
            return "[Ошибка: превышен таймаут запроса]"
        except Exception as e:
            logger.error(f"Ошибка OpenRouter OCR: {e}", exc_info=True)
            return f"[Ошибка OpenRouter OCR: {e}]"


class DummyOCRBackend:
    """Заглушка для OCR"""
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None) -> str:
        return "[OCR placeholder - OCR engine not configured]"


def run_ocr_for_blocks(blocks: List[Block], ocr_backend: OCRBackend, base_dir: str = "", 
                       image_description_backend: Optional[OCRBackend] = None,
                       index_file: Optional[str] = None,
                       prompt_loader=None) -> None:
    """
    Запустить OCR для блоков с учетом типа и категории
    
    Args:
        blocks: список блоков для обработки
        ocr_backend: движок OCR для текста и таблиц
        base_dir: базовая директория для поиска image_file
        image_description_backend: движок для описания изображений (если None, используется ocr_backend)
        index_file: путь к файлу индекса для IMAGE блоков (если указан, создается индекс)
        prompt_loader: функция для загрузки промптов из R2 (принимает имя промпта, возвращает dict с system/user)
    """
    processed = 0
    skipped = 0
    
    # Если не указан специальный движок для изображений, используем основной
    if image_description_backend is None:
        image_description_backend = ocr_backend
    
    for block in blocks:
        # Пропускаем блоки без image_file
        if not block.image_file:
            skipped += 1
            continue
        
        try:
            # Определяем полный путь к изображению
            image_path = Path(block.image_file)
            if not image_path.is_absolute() and base_dir:
                image_path = Path(base_dir) / image_path
            
            # Проверяем существование файла
            if not image_path.exists():
                logger.warning(f"Файл изображения не найден: {image_path}")
                skipped += 1
                continue
            
            # Загружаем изображение
            image = Image.open(image_path)
            
            # Получаем промпт из R2 (dict с system/user)
            prompt_data = None
            if prompt_loader:
                # Сначала пытаемся загрузить промпт категории
                if block.category:
                    prompt_data = prompt_loader(f"category_{block.category}")
                
                # Если нет промпта категории, используем промпт типа блока
                if not prompt_data:
                    if block.block_type == BlockType.IMAGE:
                        prompt_data = prompt_loader("image")
                    elif block.block_type == BlockType.TABLE:
                        prompt_data = prompt_loader("table")
                    elif block.block_type == BlockType.TEXT:
                        prompt_data = prompt_loader("text")
            
            # Обрабатываем в зависимости от типа блока
            if block.block_type == BlockType.IMAGE:
                ocr_text = image_description_backend.recognize(image, prompt=prompt_data)
                block.ocr_text = ocr_text
                
                # Если указан index_file, обновляем индекс
                if index_file:
                    from rd_core.report_md import update_smart_index  # noqa: E402
                    image_name = Path(block.image_file).name if block.image_file else f"block_{block.id}"
                    update_smart_index(ocr_text, image_name, index_file)
                
                processed += 1
                
            elif block.block_type == BlockType.TABLE:
                ocr_text = ocr_backend.recognize(image, prompt=prompt_data)
                block.ocr_text = ocr_text
                processed += 1
                
            elif block.block_type == BlockType.TEXT:
                ocr_text = ocr_backend.recognize(image, prompt=prompt_data)
                block.ocr_text = ocr_text
                processed += 1
            else:
                skipped += 1
            
        except Exception as e:
            logger.error(f"Ошибка OCR для блока {block.id}: {e}")
            skipped += 1
    
    logger.info(f"OCR завершён: {processed} блоков обработано, {skipped} пропущено")


def create_ocr_engine(backend: str = "local_vlm", **kwargs) -> OCRBackend:
    """
    Фабрика для создания OCR движка
    
    Args:
        backend: тип движка ('local_vlm', 'openrouter' или 'dummy')
        **kwargs: дополнительные параметры для движка
    
    Returns:
        Экземпляр OCR движка
    """
    if backend == "local_vlm":
        return LocalVLMBackend(**kwargs)
    elif backend == "openrouter":
        return OpenRouterBackend(**kwargs)
    elif backend == "dummy":
        return DummyOCRBackend()
    else:
        logger.warning(f"Неизвестный backend '{backend}', используется dummy")
        return DummyOCRBackend()


def generate_structured_markdown(pages: List, output_path: str, images_dir: str = "images", project_name: str = None) -> str:
    """
    Генерация markdown документа из размеченных блоков с учетом типов
    Блоки выводятся последовательно без разделения по страницам
    
    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения markdown файла
        images_dir: имя директории для изображений (относительно output_path)
        project_name: имя проекта для формирования ссылки на R2
    
    Returns:
        Путь к сохраненному файлу
    """
    try:
        from rd_core.models import Page, BlockType
        import os
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Получаем публичный URL R2
        r2_public_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
        
        # Если project_name не указан, пытаемся получить из пути
        if not project_name:
            project_name = output_file.parent.name
        
        # Собираем все блоки со всех страниц
        all_blocks = []
        for page in pages:
            for block in page.blocks:
                all_blocks.append((page.page_number, block))
        
        # Сортируем: сначала по странице, затем по вертикальной позиции
        all_blocks.sort(key=lambda x: (x[0], x[1].coords_px[1]))
        
        markdown_parts = []
        
        for page_num, block in all_blocks:
            if not block.ocr_text:
                continue
            
            category_prefix = f"**{block.category}**\n\n" if block.category else ""
            
            if block.block_type == BlockType.IMAGE:
                # Для изображений: описание + ссылка на кроп в R2
                markdown_parts.append(f"{category_prefix}")
                markdown_parts.append(f"*Изображение:*\n\n")
                markdown_parts.append(f"{block.ocr_text}\n\n")
                
                # Добавляем ссылку на кроп в R2
                if block.image_file:
                    crop_filename = Path(block.image_file).name
                    r2_url = f"{r2_public_url}/ocr_results/{project_name}/crops/{crop_filename}"
                    markdown_parts.append(f"![Изображение]({r2_url})\n\n")
            
            elif block.block_type == BlockType.TABLE:
                markdown_parts.append(f"{category_prefix}")
                markdown_parts.append(f"{block.ocr_text}\n\n")
                
            elif block.block_type == BlockType.TEXT:
                markdown_parts.append(f"{category_prefix}")
                markdown_parts.append(f"{block.ocr_text}\n\n")
        
        # Объединяем и сохраняем
        full_markdown = "".join(markdown_parts)
        output_file.write_text(full_markdown, encoding='utf-8')
        
        logger.info(f"Структурированный markdown документ сохранен: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка генерации структурированного markdown: {e}", exc_info=True)
        raise


def run_local_vlm_full_document(page_images: dict, output_path: str, api_base: str = None, model_name: str = "qwen3-vl-32b-instruct") -> str:
    """
    Распознать весь документ через локальный VLM сервер
    
    Args:
        page_images: словарь {page_num: PIL.Image}
        output_path: путь для сохранения результата
        api_base: URL VLM сервера
        model_name: имя модели
    
    Returns:
        Путь к сохраненному файлу
    """
    try:
        logger.info(f"Запуск LocalVLM OCR для {len(page_images)} страниц")
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Создаем движок
        vlm = LocalVLMBackend(api_base=api_base, model_name=model_name)
        
        # Обрабатываем страницы
        markdown_parts = []
        
        for page_num in sorted(page_images.keys()):
            logger.info(f"Обработка страницы {page_num + 1}/{len(page_images)}")
            image = page_images[page_num]
            
            # Распознаем страницу
            page_text = vlm.recognize(image)
            markdown_parts.append(f"# Страница {page_num + 1}\n\n{page_text}\n\n---\n\n")
        
        # Объединяем результаты
        full_markdown = "".join(markdown_parts)
        
        # Сохраняем
        output_file.write_text(full_markdown, encoding='utf-8')
        
        logger.info(f"Markdown документ сохранен: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке документа LocalVLM OCR: {e}", exc_info=True)
        raise
