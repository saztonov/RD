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
from app.models import Block, BlockType

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


# Папка с промптами
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(prompt_file: str) -> str:
    """
    Загрузить промпт из файла в папке prompts/
    
    Args:
        prompt_file: имя файла (например "ocr_text.txt")
    
    Returns:
        Текст промпта или дефолтный текст при ошибке
    """
    try:
        prompt_path = PROMPTS_DIR / prompt_file
        
        if prompt_path.exists():
            text = prompt_path.read_text(encoding='utf-8').strip()
            logger.debug(f"Промпт загружен из {prompt_file}")
            return text
        else:
            logger.warning(f"Файл промпта не найден: {prompt_path}")
            return ""
    except Exception as e:
        logger.error(f"Ошибка загрузки промпта {prompt_file}: {e}")
        return ""


class OCRBackend(Protocol):
    """
    Интерфейс для OCR-движков
    """
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """
        Распознать текст на изображении
        
        Args:
            image: изображение для распознавания
            prompt: кастомный промпт (опционально)
        
        Returns:
            Распознанный текст
        """
        ...


class LocalVLMBackend:
    """OCR через ngrok endpoint (проксирует в LM Studio)"""
    
    def __init__(self, api_base: str = None, model_name: str = "qwen3-vl-32b-instruct"):
        self.model_name = model_name
        try:
            import httpx
            self.httpx = httpx
        except ImportError:
            raise ImportError("Требуется установить httpx: pip install httpx")
        logger.info(f"LocalVLM инициализирован (модель: {self.model_name})")
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """Распознать текст через ngrok endpoint"""
        try:
            from app.config import get_lm_base_url
            
            if not prompt:
                prompt = load_prompt("ocr_full_page.txt")
            
            img_base64 = image_to_base64(image)
            url = get_lm_base_url()
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON or Markdown formats with 100% accuracy. Do not omit details. Do not hallucinate values."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
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
    
    def __init__(self, api_key: str, model_name: str = "qwen/qwen3-vl-30b-a3b-instruct"):
        self.api_key = api_key
        self.model_name = model_name
        try:
            import requests
            self.requests = requests
        except ImportError:
            raise ImportError("Требуется установить requests: pip install requests")
        logger.info(f"OpenRouter инициализирован (модель: {self.model_name})")
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """Распознать текст через OpenRouter API"""
        try:
            image_b64 = image_to_base64(image)
            user_prompt = prompt if prompt else "Распознай весь текст с этого изображения. Верни только текст, без комментариев."
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an expert design engineer and automation specialist. Your task is to analyze technical drawings and extract data into structured JSON or Markdown formats with 100% accuracy. Do not omit details. Do not hallucinate values."
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
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        return "[OCR placeholder - OCR engine not configured]"


def run_ocr_for_blocks(blocks: List[Block], ocr_backend: OCRBackend, base_dir: str = "", 
                       image_description_backend: Optional[OCRBackend] = None,
                       index_file: Optional[str] = None) -> None:
    """
    Запустить OCR для блоков с учетом типа:
    - TEXT/TABLE: распознавание текста
    - IMAGE: детальное описание на русском языке
    
    Args:
        blocks: список блоков для обработки
        ocr_backend: движок OCR для текста и таблиц
        base_dir: базовая директория для поиска image_file
        image_description_backend: движок для описания изображений (если None, используется ocr_backend)
        index_file: путь к файлу индекса для IMAGE блоков (если указан, создается индекс)
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
            
            # Обрабатываем в зависимости от типа блока
            if block.block_type == BlockType.IMAGE:
                # Для изображений - детальное описание из промпта
                image_prompt = load_prompt("ocr_image_description.txt")
                ocr_text = image_description_backend.recognize(image, prompt=image_prompt)
                block.ocr_text = ocr_text
                
                # Если указан index_file, обновляем индекс
                if index_file:
                    from app.report_md import update_smart_index
                    image_name = Path(block.image_file).name if block.image_file else f"block_{block.id}"
                    update_smart_index(ocr_text, image_name, index_file)
                
                processed += 1
                
            elif block.block_type == BlockType.TABLE:
                # Для таблиц - специальный промпт
                table_prompt = load_prompt("ocr_table.txt")
                if table_prompt:
                    ocr_text = ocr_backend.recognize(image, prompt=table_prompt)
                else:
                    ocr_text = ocr_backend.recognize(image)
                block.ocr_text = ocr_text
                processed += 1
                
            elif block.block_type == BlockType.TEXT:
                # Для текста - специальный промпт
                text_prompt = load_prompt("ocr_text.txt")
                if text_prompt:
                    ocr_text = ocr_backend.recognize(image, prompt=text_prompt)
                else:
                    ocr_text = ocr_backend.recognize(image)
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


def generate_structured_markdown(pages: List, output_path: str, images_dir: str = "images") -> str:
    """
    Генерация markdown документа из размеченных блоков с учетом типов
    
    Args:
        pages: список Page объектов с блоками
        output_path: путь для сохранения markdown файла
        images_dir: имя директории для изображений (относительно output_path)
    
    Returns:
        Путь к сохраненному файлу
    """
    try:
        from app.models import Page, BlockType
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        markdown_parts = []
        
        for page in pages:
            page_num = page.page_number
            markdown_parts.append(f"# Страница {page_num + 1}\n\n")
            
            # Сортируем блоки по вертикальной позиции (сверху вниз)
            sorted_blocks = sorted(page.blocks, key=lambda b: b.coords_px[1])
            
            for block in sorted_blocks:
                if not block.ocr_text:
                    continue
                
                category_prefix = f"**{block.category}**\n\n" if block.category else ""
                
                if block.block_type == BlockType.IMAGE:
                    # Для изображений: описание + ссылка на кроп
                    markdown_parts.append(f"{category_prefix}")
                    markdown_parts.append(f"*Изображение:*\n\n")
                    markdown_parts.append(f"{block.ocr_text}\n\n")
                    
                    # Добавляем ссылку на кроп, если есть image_file
                    if block.image_file:
                        # Конвертируем путь к кропу в относительный
                        crop_path = Path(block.image_file)
                        if crop_path.is_absolute():
                            # Пытаемся сделать относительным к output_path
                            try:
                                rel_path = crop_path.relative_to(output_file.parent)
                                # Конвертируем в POSIX путь (прямые слэши)
                                rel_path_str = rel_path.as_posix()
                                markdown_parts.append(f"![Изображение]({rel_path_str})\n\n")
                            except ValueError:
                                # Если не получается сделать относительным, используем абсолютный
                                crop_path_str = crop_path.as_posix()
                                markdown_parts.append(f"![Изображение]({crop_path_str})\n\n")
                        else:
                            # Конвертируем в POSIX путь (прямые слэши)
                            crop_path_str = crop_path.as_posix()
                            markdown_parts.append(f"![Изображение]({crop_path_str})\n\n")
                    
                elif block.block_type == BlockType.TABLE:
                    # Для таблиц
                    markdown_parts.append(f"{category_prefix}")
                    markdown_parts.append(f"{block.ocr_text}\n\n")
                    
                elif block.block_type == BlockType.TEXT:
                    # Для текста
                    markdown_parts.append(f"{category_prefix}")
                    markdown_parts.append(f"{block.ocr_text}\n\n")
            
            markdown_parts.append("---\n\n")
        
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
