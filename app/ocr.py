"""
OCR обработка через различные движки
Поддержка Chandra OCR и локальных VLM серверов (Qwen3-VL и др.)
"""

import logging
import tempfile
import subprocess
import shutil
import json
import base64
import io
from pathlib import Path
from typing import Protocol, List, Optional
from PIL import Image
from app.models import Block, BlockType

logger = logging.getLogger(__name__)


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
    """
    OCR через локальный VLM сервер (Qwen3-VL, LLaVA и др.)
    Использует OpenAI-совместимый API
    """
    
    def __init__(self, api_base: str = "http://127.0.0.1:1234/v1", model_name: str = "qwen3-vl-32b-instruct"):
        """
        Args:
            api_base: URL сервера (например http://127.0.0.1:1234/v1)
            model_name: имя модели на сервере
        """
        self.api_base = api_base.rstrip('/')
        self.model_name = model_name
        
        try:
            import requests
            self.requests = requests
        except ImportError:
            raise ImportError("Требуется установить requests: pip install requests")
        
        logger.info(f"LocalVLM инициализирован (сервер: {self.api_base}, модель: {self.model_name})")
    
    def _image_to_base64(self, image: Image.Image) -> str:
        """Конвертировать PIL Image в base64"""
        # Сжимаем если изображение больше 1500px
        max_size = 1500
        if image.width > max_size or image.height > max_size:
            ratio = min(max_size / image.width, max_size / image.height)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.LANCZOS)
        
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        img_bytes = buffer.getvalue()
        return base64.b64encode(img_bytes).decode('utf-8')
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """
        Распознать текст через локальный VLM сервер
        
        Args:
            image: изображение для распознавания
            prompt: промпт для модели (если None, загружается из prompts/ocr_full_page.txt)
        
        Returns:
            Распознанный текст
        """
        try:
            # Дефолтный промпт для OCR из файла
            if not prompt:
                prompt = load_prompt("ocr_full_page.txt")
            
            # Конвертируем изображение в base64
            img_base64 = self._image_to_base64(image)
            
            # Формируем запрос в OpenAI формате
            url = f"{self.api_base}/chat/completions"
            
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
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_base64}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 16384,
                "temperature": 0.1,
                "top_p": 0.9,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0
            }
            
            # Отправляем запрос
            response = self.requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=90
            )
            
            if response.status_code != 200:
                logger.error(f"VLM сервер ошибка: {response.status_code} - {response.text}")
                return f"[Ошибка VLM: HTTP {response.status_code}]"
            
            # Парсим ответ
            result = response.json()
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if not text:
                logger.error(f"Пустой ответ от VLM сервера: {result}")
                return "[Ошибка: пустой ответ от сервера]"
            
            logger.debug(f"VLM OCR: распознано {len(text)} символов")
            return text.strip()
            
        except self.requests.exceptions.ConnectionError:
            logger.error(f"Не удалось подключиться к VLM серверу: {self.api_base}")
            return "[Ошибка: сервер недоступен]"
        except self.requests.exceptions.Timeout:
            logger.error("VLM сервер: превышен таймаут")
            return "[Ошибка: таймаут сервера]"
        except Exception as e:
            logger.error(f"Ошибка VLM OCR: {e}", exc_info=True)
            return f"[Ошибка VLM OCR: {e}]"


class ChandraOCRBackend:
    """
    OCR через Chandra (datalab-to/chandra)
    Использует CLI интерфейс через subprocess
    """
    
    def __init__(self, method: str = "hf", vllm_api_base: str = "http://localhost:8000/v1"):
        """
        Args:
            method: метод инференса ('hf' или 'vllm')
            vllm_api_base: URL vLLM сервера (если method='vllm')
        """
        self.method = method
        self.vllm_api_base = vllm_api_base
        
        # Проверяем установку chandra
        if not shutil.which("chandra"):
            raise ImportError(
                "Требуется установить chandra-ocr:\n"
                "pip install chandra-ocr"
            )
        
        logger.info(f"ChandraOCR инициализирован (метод: {method})")
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """
        Распознать текст через Chandra
        
        Args:
            image: изображение для распознавания
            prompt: игнорируется (Chandra не использует промпты)
        
        Returns:
            Распознанный текст в Markdown формате
        """
        try:
            # Создаем временные файлы
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                
                # Сохраняем изображение
                img_path = tmp_path / "input.png"
                image.save(img_path, 'PNG')
                
                # Директория для вывода
                output_dir = tmp_path / "output"
                output_dir.mkdir()
                
                # Запускаем Chandra через CLI
                cmd = [
                    "chandra",
                    str(img_path),
                    str(output_dir),
                    "--method", self.method,
                    "--no-images"  # Не извлекаем изображения для отдельных блоков
                ]
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 минут таймаут
                )
                
                if result.returncode != 0:
                    logger.error(f"Chandra CLI ошибка: {result.stderr}")
                    return f"[Ошибка Chandra OCR: {result.stderr}]"
                
                # Читаем результат - Chandra создает подпапку с именем файла
                md_file = output_dir / "input" / "input.md"
                if not md_file.exists():
                    # Пробуем альтернативный путь
                    md_files = list(output_dir.rglob("*.md"))
                    if md_files:
                        md_file = md_files[0]
                    else:
                        logger.error(f"Не найден .md файл в {output_dir}")
                        return "[Ошибка: результат не найден]"
                
                text = md_file.read_text(encoding='utf-8')
                logger.debug(f"Chandra OCR: распознано {len(text)} символов")
                return text.strip()
                
        except subprocess.TimeoutExpired:
            logger.error("Chandra OCR: превышен таймаут")
            return "[Ошибка: таймаут распознавания]"
        except Exception as e:
            logger.error(f"Ошибка Chandra OCR: {e}", exc_info=True)
            return f"[Ошибка Chandra OCR: {e}]"


class OpenRouterBackend:
    """
    OCR через OpenRouter API (qwen/qwen3-vl-30b-a3b-instruct)
    """
    
    def __init__(self, api_key: str, model_name: str = "qwen/qwen3-vl-30b-a3b-instruct"):
        """
        Args:
            api_key: OpenRouter API ключ
            model_name: имя модели на OpenRouter
        """
        self.api_key = api_key
        self.model_name = model_name
        
        try:
            import requests
            self.requests = requests
        except ImportError:
            raise ImportError("Требуется установить requests: pip install requests")
        
        logger.info(f"OpenRouter инициализирован (модель: {self.model_name})")
    
    def _image_to_base64(self, image: Image.Image) -> str:
        """Конвертировать PIL Image в base64"""
        max_size = 1500
        if image.width > max_size or image.height > max_size:
            ratio = min(max_size / image.width, max_size / image.height)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.LANCZOS)
        
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """
        Распознать текст через OpenRouter API
        """
        try:
            image_b64 = self._image_to_base64(image)
            
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
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                            }
                        ]
                    }
                ],
                "max_tokens": 16384,
                "temperature": 0.1,
                "top_p": 0.9
            }
            
            response = self.requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
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
    """
    Заглушка для OCR (для тестирования)
    """
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """Возвращает заглушку"""
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
        backend: тип движка ('local_vlm', 'openrouter', 'chandra' или 'dummy')
        **kwargs: дополнительные параметры для движка
    
    Returns:
        Экземпляр OCR движка
    """
    if backend == "local_vlm":
        return LocalVLMBackend(**kwargs)
    elif backend == "openrouter":
        return OpenRouterBackend(**kwargs)
    elif backend == "chandra":
        return ChandraOCRBackend(**kwargs)
    elif backend == "dummy":
        return DummyOCRBackend()
    else:
        logger.warning(f"Неизвестный backend '{backend}', используется dummy")
        return DummyOCRBackend()


def run_chandra_ocr_full_document(page_images: dict, output_path: str, method: str = "hf") -> str:
    """
    Распознать весь документ с Chandra OCR и создать единый Markdown файл
    
    Args:
        page_images: словарь {page_num: PIL.Image}
        output_path: путь для сохранения результата
        method: метод инференса ('hf' или 'vllm')
    
    Returns:
        Путь к сохраненному файлу
    """
    try:
        logger.info(f"Запуск Chandra OCR для {len(page_images)} страниц")
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Создаем временную директорию
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_dir = tmp_path / "input"
            output_dir = tmp_path / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            
            # Сохраняем страницы как изображения
            for page_num in sorted(page_images.keys()):
                image = page_images[page_num]
                img_path = input_dir / f"page_{page_num:04d}.png"
                image.save(img_path, 'PNG')
            
            # Запускаем Chandra для каждой страницы
            markdown_parts = []
            
            for page_num in sorted(page_images.keys()):
                logger.info(f"Обработка страницы {page_num + 1}/{len(page_images)}")
                
                img_path = input_dir / f"page_{page_num:04d}.png"
                page_output_dir = output_dir / f"page_{page_num:04d}"
                page_output_dir.mkdir()
                
                # CLI команда
                cmd = [
                    "chandra",
                    str(img_path),
                    str(page_output_dir),
                    "--method", method,
                    "--include-images"  # Включаем извлечение изображений
                ]
                
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    
                    if result.returncode != 0:
                        logger.error(f"Ошибка на странице {page_num}: {result.stderr}")
                        markdown_parts.append(f"# Страница {page_num + 1}\n\n[Ошибка распознавания]\n\n---\n\n")
                        continue
                    
                    # Читаем результат
                    md_files = list(page_output_dir.rglob("*.md"))
                    if md_files:
                        page_text = md_files[0].read_text(encoding='utf-8')
                        markdown_parts.append(f"# Страница {page_num + 1}\n\n{page_text}\n\n---\n\n")
                        
                        # Копируем изображения если есть
                        images_src = page_output_dir / f"page_{page_num:04d}" / "images"
                        if images_src.exists():
                            images_dst = output_file.parent / "images"
                            images_dst.mkdir(exist_ok=True)
                            for img_file in images_src.iterdir():
                                new_name = f"page{page_num}_{img_file.name}"
                                shutil.copy2(img_file, images_dst / new_name)
                    else:
                        logger.warning(f"Не найден .md файл для страницы {page_num}")
                        markdown_parts.append(f"# Страница {page_num + 1}\n\n[Результат не найден]\n\n---\n\n")
                
                except subprocess.TimeoutExpired:
                    logger.error(f"Таймаут на странице {page_num}")
                    markdown_parts.append(f"# Страница {page_num + 1}\n\n[Таймаут]\n\n---\n\n")
            
            # Объединяем результаты
            full_markdown = "".join(markdown_parts)
            
            # Сохраняем
            output_file.write_text(full_markdown, encoding='utf-8')
            
            logger.info(f"Markdown документ сохранен: {output_file}")
            return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке документа Chandra OCR: {e}", exc_info=True)
        raise


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


def run_local_vlm_full_document(page_images: dict, output_path: str, api_base: str = "http://127.0.0.1:1234/v1", model_name: str = "qwen3-vl-32b-instruct") -> str:
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
