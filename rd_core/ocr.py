"""
OCR обработка через API движки
Поддержка OpenRouter и Datalab API
"""

import logging
import base64
import io
import re
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


def image_to_pdf_base64(image: Image.Image) -> str:
    """
    Конвертировать PIL Image в PDF base64 (векторное качество)
    
    Args:
        image: PIL изображение
    
    Returns:
        Base64 строка PDF
    """
    buffer = io.BytesIO()
    # Конвертируем в RGB если нужно (PDF не поддерживает RGBA)
    if image.mode == 'RGBA':
        rgb_image = Image.new('RGB', image.size, (255, 255, 255))
        rgb_image.paste(image, mask=image.split()[3])
        image = rgb_image
    elif image.mode != 'RGB':
        image = image.convert('RGB')
    
    image.save(buffer, format='PDF', resolution=300.0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')




class OCRBackend(Protocol):
    """
    Интерфейс для OCR-движков
    """
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None) -> str:
        """
        Распознать текст на изображении
        
        Args:
            image: изображение для распознавания
            prompt: dict с ключами 'system' и 'user' (опционально)
            json_mode: принудительный JSON режим вывода
        
        Returns:
            Распознанный текст
        """
        ...


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
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None) -> str:
        """Распознать текст через OpenRouter API
        
        Args:
            image: изображение для распознавания
            prompt: dict с ключами 'system' и 'user'
            json_mode: принудительный JSON режим (None = автоопределение по промпту)
        """
        try:
            # Получаем порядок провайдеров (кэшируется)
            if self._provider_order is None:
                self._provider_order = self._fetch_cheapest_providers() or []
            
            # Извлекаем system и user из промта
            if prompt and isinstance(prompt, dict):
                system_prompt = prompt.get("system", "") or self.DEFAULT_SYSTEM
                user_prompt = prompt.get("user", "") or self.DEFAULT_USER
            else:
                system_prompt = self.DEFAULT_SYSTEM
                user_prompt = self.DEFAULT_USER
            
            # Автоопределение JSON mode по промпту
            if json_mode is None:
                prompt_text = (system_prompt + user_prompt).lower()
                json_mode = "json" in prompt_text and ("верни" in prompt_text or "return" in prompt_text)
            
            # Специальные параметры для Gemini 3 Flash
            is_gemini3 = "gemini-3" in self.model_name.lower()
            
            # Для Gemini 3 отправляем PDF (векторный формат), иначе PNG
            if is_gemini3:
                file_b64 = image_to_pdf_base64(image)
                media_type = "application/pdf"
            else:
                file_b64 = image_to_base64(image)
                media_type = "image/png"
            
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
                            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{file_b64}"}}
                        ]
                    }
                ],
                "max_tokens": 16384,
                "temperature": 0.0 if is_gemini3 else 0.1,
                "top_p": 0.9
            }
            
            # JSON mode для структурированного вывода
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            
            # Gemini 3 специфичные параметры через transforms
            if is_gemini3:
                payload["transforms"] = {
                    "media_resolution": "MEDIA_RESOLUTION_HIGH"
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
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None) -> str:
        return "[OCR placeholder - OCR engine not configured]"


class DatalabOCRBackend:
    """OCR через Datalab Marker API"""
    
    API_URL = "https://www.datalab.to/api/v1/marker"
    POLL_INTERVAL = 3
    MAX_POLL_ATTEMPTS = 180  # ~9 минут ожидания
    MAX_RETRIES = 3  # Количество попыток при 429
    MAX_WIDTH = 4000  # Максимальная ширина изображения (Datalab ограничение)
    
    # Промпт для коррекции блоков (Russian Construction Documentation QA)
    BLOCK_CORRECTION_PROMPT = """You are a specialized QA OCR assistant for Russian Construction Documentation (Stages P & RD). Your goal is to transcribe image blocks into strict Markdown for automated error checking.

RULES:
1. **Content Fidelity (CRITICAL)**: Transcribe text and numbers EXACTLY as seen. 
   - NEVER "fix" math errors. If the sum in the image is wrong, keep it wrong. We need to find these errors.
   - NEVER round numbers. Preserve all decimals (e.g., "34,5").
2. **Tables**: If the image shows a table (Explication, Bill of Materials), output a VALID Markdown table.
   - If headers are cut off (missing from the image), output the data rows as a table without inventing headers.
   - Preserve merged cell content if implied.
3. **Abbreviations**: Keep Russian technical acronyms exactly as printed: "МХМТС", "БКТ", "ПУИ", "ВРУ", "ЛК", "С/у". Do not expand them.
4. **OCR Correction**: Fix ONLY visual character errors typical for Cyrillic OCR:
   - '0' (digit) vs 'O' (letter)
   - '3' (digit) vs 'З' (letter)
   - 'б' (letter) vs '6' (digit)
   - 'м2' -> 'м²'
5. **Drawings**: If the image is a drawing (e.g., parking layout), output a bulleted list of text labels and dimensions found (e.g., "- Малое м/м: 2600x5300").
6. **Output**: Return ONLY the clean Markdown. No conversational filler."""
    
    def __init__(self, api_key: str, rate_limiter=None):
        """
        Args:
            api_key: API ключ Datalab
            rate_limiter: объект rate limiter с методами acquire()/release()
        """
        if not api_key:
            raise ValueError("DATALAB_API_KEY не указан")
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}
        self.rate_limiter = rate_limiter
        try:
            import requests
            self.requests = requests
        except ImportError:
            raise ImportError("Требуется установить requests: pip install requests")
        logger.info("Datalab OCR инициализирован")
    
    def recognize(self, image: Image.Image, prompt: Optional[dict] = None, json_mode: bool = None) -> str:
        """Распознать изображение через Datalab API (json_mode игнорируется)"""
        import tempfile
        import time
        import os
        
        # Получаем разрешение от rate limiter (если задан)
        if self.rate_limiter:
            if not self.rate_limiter.acquire():
                return "[Ошибка: таймаут ожидания rate limiter]"
        
        try:
            # Пропорциональное сжатие широких изображений (таблиц)
            if image.width > self.MAX_WIDTH:
                ratio = self.MAX_WIDTH / image.width
                new_width = self.MAX_WIDTH
                new_height = int(image.height * ratio)
                logger.info(f"Сжатие изображения {image.width}x{image.height} -> {new_width}x{new_height}")
                image = image.resize((new_width, new_height), Image.LANCZOS)
            
            # Сохраняем изображение во временный файл
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                image.save(tmp, format='PNG')
                tmp_path = tmp.name
            
            try:
                # Отправляем на распознавание с retry для 429
                response = None
                for retry in range(self.MAX_RETRIES):
                    with open(tmp_path, 'rb') as f:
                        files = {'file': (os.path.basename(tmp_path), f, 'image/png')}
                        data = {
                            'mode': 'accurate',
                            'force_ocr': 'true',
                            'paginate': 'false',
                            'use_llm': 'true',
                            'output_format': 'markdown',
                            'disable_image_extraction': 'true',
                            'block_correction_prompt': self.BLOCK_CORRECTION_PROMPT
                        }
                        
                        response = self.requests.post(
                            self.API_URL,
                            headers=self.headers,
                            files=files,
                            data=data,
                            timeout=120
                        )
                    
                    if response.status_code == 429:
                        # Rate limit - exponential backoff
                        wait_time = min(60, (2 ** retry) * 10)
                        logger.warning(f"Datalab API 429: ждём {wait_time}с (попытка {retry + 1}/{self.MAX_RETRIES})")
                        time.sleep(wait_time)
                        continue
                    break
                
                if response is None or response.status_code == 429:
                    return "[Ошибка Datalab API: превышен лимит запросов (429)]"
                
                if response.status_code != 200:
                    logger.error(f"Datalab API error: {response.status_code} - {response.text}")
                    return f"[Ошибка Datalab API: {response.status_code}]"
                
                result = response.json()
                
                if not result.get('success'):
                    error = result.get('error', 'Unknown error')
                    return f"[Ошибка Datalab: {error}]"
                
                # Получаем URL для поллинга
                check_url = result.get('request_check_url')
                if not check_url:
                    if 'markdown' in result:
                        return result['markdown']
                    return "[Ошибка: нет request_check_url]"
                
                # Поллинг результата
                logger.info(f"Datalab: начало поллинга результата по URL: {check_url}")
                for attempt in range(self.MAX_POLL_ATTEMPTS):
                    time.sleep(self.POLL_INTERVAL)
                    
                    logger.debug(f"Datalab: попытка поллинга {attempt + 1}/{self.MAX_POLL_ATTEMPTS}")
                    poll_response = self.requests.get(check_url, headers=self.headers, timeout=30)
                    
                    if poll_response.status_code == 429:
                        # Rate limit на поллинге - ждём и продолжаем
                        logger.warning("Datalab: 429 при поллинге, ждём 30с")
                        time.sleep(30)
                        continue
                    
                    if poll_response.status_code != 200:
                        logger.warning(f"Datalab: поллинг вернул статус {poll_response.status_code}: {poll_response.text}")
                        continue
                    
                    poll_result = poll_response.json()
                    status = poll_result.get('status', '')
                    
                    logger.info(f"Datalab: текущий статус задачи: '{status}' (попытка {attempt + 1}/{self.MAX_POLL_ATTEMPTS})")
                    
                    if status == 'complete':
                        logger.info("Datalab: задача успешно завершена")
                        return poll_result.get('markdown', '')
                    elif status == 'failed':
                        error = poll_result.get('error', 'Unknown error')
                        logger.error(f"Datalab: задача завершилась с ошибкой: {error}")
                        return f"[Ошибка Datalab: {error}]"
                    elif status not in ['processing', 'pending', 'queued']:
                        logger.warning(f"Datalab: неизвестный статус '{status}'. Полный ответ: {poll_result}")
                
                logger.error(f"Datalab: превышено время ожидания после {self.MAX_POLL_ATTEMPTS} попыток")
                return "[Ошибка Datalab: превышено время ожидания]"
                
            finally:
                # Удаляем временный файл
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                    
        except Exception as e:
            logger.error(f"Ошибка Datalab OCR: {e}", exc_info=True)
            return f"[Ошибка Datalab OCR: {e}]"
        finally:
            # Освобождаем rate limiter
            if self.rate_limiter:
                self.rate_limiter.release()


def create_ocr_engine(backend: str = "dummy", **kwargs) -> OCRBackend:
    """
    Фабрика для создания OCR движка
    
    Args:
        backend: тип движка ('openrouter', 'datalab' или 'dummy')
        **kwargs: дополнительные параметры для движка
    
    Returns:
        Экземпляр OCR движка
    """
    if backend == "openrouter":
        return OpenRouterBackend(**kwargs)
    elif backend == "datalab":
        return DatalabOCRBackend(**kwargs)
    elif backend == "dummy":
        return DummyOCRBackend()
    else:
        logger.warning(f"Неизвестный backend '{backend}', используется dummy")
        return DummyOCRBackend()


def generate_structured_markdown(pages: List, output_path: str, images_dir: str = "images", project_name: str = None, doc_name: str = None) -> str:
    """
    Генерация markdown документа из размеченных блоков с учетом типов
    Блоки выводятся последовательно без разделения по страницам
    
    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения markdown файла
        images_dir: имя директории для изображений (относительно output_path)
        project_name: имя проекта для формирования ссылки на R2
        doc_name: имя документа PDF
    
    Returns:
        Путь к сохраненному файлу
    """
    try:
        from rd_core.models import Page, BlockType
        import os
        import json as json_module
        
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
            
            # Нормализуем текст: убираем лишние пустые строки
            text = block.ocr_text.strip()
            if not text:
                continue
            
            # Убираем множественные переносы строк (оставляем максимум 2)
            text = re.sub(r'\n{3,}', '\n\n', text)
            
            if block.block_type == BlockType.IMAGE:
                # Для IMAGE блоков: собираем JSON с метаданными
                # Парсим analysis из ocr_text (модель возвращает JSON)
                analysis = None
                try:
                    # Пробуем найти JSON в тексте
                    json_match = re.search(r'\{[\s\S]*\}', text)
                    if json_match:
                        analysis = json_module.loads(json_match.group(0))
                    else:
                        # Если JSON не найден, используем текст как есть
                        analysis = {"raw_text": text}
                except json_module.JSONDecodeError:
                    analysis = {"raw_text": text}
                
                # Формируем URI изображения
                image_uri = ""
                mime_type = "image/png"
                if block.image_file:
                    crop_filename = Path(block.image_file).name
                    image_uri = f"{r2_public_url}/ocr_results/{project_name}/crops/{crop_filename}"
                    # Определяем mime_type по расширению
                    ext = Path(block.image_file).suffix.lower()
                    if ext == ".pdf":
                        mime_type = "application/pdf"
                    elif ext in (".jpg", ".jpeg"):
                        mime_type = "image/jpeg"
                
                # Собираем финальный JSON объект
                final_json = {
                    "doc_metadata": {
                        "doc_name": doc_name or "",
                        "page": page_num + 1 if page_num is not None else None,
                        "operator_hint": block.hint or ""
                    },
                    "image": {
                        "uri": image_uri,
                        "mime_type": mime_type
                    },
                    "raw_pdfplumber_text": block.pdfplumber_text or "",
                    "analysis": analysis
                }
                
                # Сериализуем через json-энкодер
                json_str = json_module.dumps(final_json, ensure_ascii=False, indent=2)
                markdown_parts.append(f"```json\n{json_str}\n```\n\n")
            
            elif block.block_type == BlockType.TABLE:
                markdown_parts.append(f"{text}\n\n")
                
            elif block.block_type == BlockType.TEXT:
                markdown_parts.append(f"{text}\n\n")
        
        # Объединяем и сохраняем
        full_markdown = "".join(markdown_parts)
        output_file.write_text(full_markdown, encoding='utf-8')
        
        logger.info(f"Структурированный markdown документ сохранен: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка генерации структурированного markdown: {e}", exc_info=True)
        raise
