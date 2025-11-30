"""
OCR обработка блоков
Абстракция над OCR-движками (pytesseract, HunyuanOCR)
"""

import logging
from pathlib import Path
from typing import Protocol, List, Optional
from PIL import Image
import pytesseract
import torch
from app.models import Block, BlockType

logger = logging.getLogger(__name__)


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


class TesseractOCRBackend:
    """
    OCR через Tesseract (pytesseract)
    
    Требует установленного Tesseract:
    - Windows: скачать с https://github.com/UB-Mannheim/tesseract/wiki
    - Указать путь: pytesseract.pytesseract.tesseract_cmd = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'
    """
    
    def __init__(self, lang: str = 'rus+eng', tesseract_path: Optional[str] = None):
        """
        Args:
            lang: языки для распознавания (например 'rus+eng')
            tesseract_path: путь к tesseract.exe (если None, берётся из PATH)
        """
        self.lang = lang
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            logger.info(f"Tesseract путь установлен: {tesseract_path}")
        
        logger.info(f"TesseractOCRBackend инициализирован (языки: {lang})")
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """
        Распознать текст через Tesseract
        
        Args:
            image: изображение для распознавания
            prompt: игнорируется для Tesseract
        
        Returns:
            Распознанный текст
        """
        try:
            text = pytesseract.image_to_string(image, lang=self.lang)
            result = text.strip()
            logger.debug(f"OCR выполнен: {len(result)} символов распознано")
            return result
        except pytesseract.TesseractNotFoundError:
            # Логируем ошибку один раз или более явно, возвращаем понятную строку
            err_msg = "[Tesseract не найден]"
            logger.error("Tesseract не найден. Установите Tesseract и добавьте путь в PATH или конфиг.")
            return err_msg
        except Exception as e:
            logger.error(f"Ошибка OCR: {e}")
            return f"[Ошибка OCR: {e}]"


class DummyOCRBackend:
    """
    Заглушка для OCR (для тестирования без Tesseract)
    """
    
    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """Возвращает заглушку"""
        return "[OCR placeholder - Tesseract not configured]"


class HunyuanOCRBackend:
    """
    OCR через HunyuanOCR (Tencent VLM)
    Использует Hugging Face Transformers.
    """
    
    def __init__(self, model_path: str = "tencent/HunyuanOCR"):
        """
        Args:
            model_path: путь к модели или имя на HF Hub
        """
        try:
            from transformers import AutoProcessor, HunYuanVLForConditionalGeneration
            
            logger.info("Инициализация HunyuanOCR (Transformers)...")
            
            self.processor = AutoProcessor.from_pretrained(model_path, use_fast=False)
            self.model = HunYuanVLForConditionalGeneration.from_pretrained(
                model_path,
                attn_implementation="eager",
                dtype=torch.bfloat16,
                device_map="auto"
            )
            
            self.default_prompt = (
                "提取文档图片中正文的所有信息用markdown格式表示，其中页眉、页脚部分忽略，表格用html格式表达，文档中公式用latex格式表示，按照阅读顺序组织进行解析。"
                # Перевод: "Извлеките всю информацию из основного текста изображения документа в формате markdown, 
                # игнорируя заголовки и колонтитулы, таблицы в формате html, формулы в latex, 
                # организовав разбор в порядке чтения."
            )
            
            logger.info("HunyuanOCR инициализирован успешно")
            
        except ImportError as e:
            logger.error(f"Не удалось импортировать transformers: {e}")
            raise ImportError(
                "Требуется библиотека transformers (версия с поддержкой HunyuanOCR). "
                "Выполните: pip install git+https://github.com/huggingface/transformers@82a06db03535c49aa987719ed0746a76093b1ec4"
            )
        except Exception as e:
            logger.error(f"Ошибка инициализации HunyuanOCR: {e}")
            raise

    def _clean_repeated_substrings(self, text: str) -> str:
        """Очистка повторяющихся подстрок (из официального скрипта)"""
        n = len(text)
        if n < 8000:
            return text
        for length in range(2, n // 10 + 1):
            candidate = text[-length:] 
            count = 0
            i = n - length
            
            while i >= 0 and text[i:i + length] == candidate:
                count += 1
                i -= length

            if count >= 10:
                return text[:n - length * (count - 1)]  

        return text

    def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str:
        """
        Распознать текст через HunyuanOCR
        
        Args:
            image: изображение для распознавания
            prompt: кастомный промпт
        
        Returns:
            Распознанный текст в Markdown формате
        """
        try:
            actual_prompt = prompt if prompt else self.default_prompt
            
            # Подготовка сообщений (список сообщений для одного диалога)
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": actual_prompt},
                    ],
                }
            ]
            
            # apply_chat_template принимает список сообщений (диалог)
            text_prompt = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            
            texts = [text_prompt]
            
            # Подготовка инпутов
            inputs = self.processor(
                text=texts,
                images=image,
                padding=True,
                return_tensors="pt",
            )
            
            # Инференс
            with torch.no_grad():
                device = next(self.model.parameters()).device
                inputs = inputs.to(device)
                
                generated_ids = self.model.generate(
                    **inputs, 
                    max_new_tokens=2048, # Увеличил токенов для больших доков
                    do_sample=False
                )
                
            # Декодирование
            if "input_ids" in inputs:
                input_ids = inputs.input_ids
            else:
                input_ids = inputs.inputs
                
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(input_ids, generated_ids)
            ]
            
            output_text = self.processor.batch_decode(
                generated_ids_trimmed, 
                skip_special_tokens=True, 
                clean_up_tokenization_spaces=False
            )[0]
            
            result = self._clean_repeated_substrings(output_text)
            logger.debug(f"HunyuanOCR: распознано {len(result)} символов")
            return result.strip()
            
        except Exception as e:
            logger.error(f"Ошибка HunyuanOCR распознавания: {e}")
            return f"[Ошибка HunyuanOCR: {e}]"


def run_ocr_for_blocks(blocks: List[Block], ocr_backend: OCRBackend, base_dir: str = "") -> None:
    """
    Запустить OCR для блоков типа TEXT или TABLE
    """
    processed = 0
    skipped = 0
    
    for block in blocks:
        # Пропускаем блоки типа IMAGE
        if block.block_type == BlockType.IMAGE:
            # logger.debug(f"Блок {block.id} (IMAGE) пропущен - OCR не нужен")
            skipped += 1
            continue
        
        # Пропускаем блоки без image_file
        if not block.image_file:
            # logger.warning(f"Блок {block.id} не имеет image_file, пропускаем")
            skipped += 1
            continue
        
        # Проверяем, что тип TEXT или TABLE
        if block.block_type not in (BlockType.TEXT, BlockType.TABLE):
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
            
            # Запускаем OCR
            # Для блоков используем специфичный промпт если это Hunyuan
            block_prompt = None
            if isinstance(ocr_backend, HunyuanOCRBackend):
                 # Простой промпт для транскрипции фрагмента
                 block_prompt = "Transcribe the content of this image fragment to Markdown."

            ocr_text = ocr_backend.recognize(image, prompt=block_prompt)
            
            # Сохраняем результат в блок
            block.ocr_text = ocr_text
            processed += 1
            
        except Exception as e:
            logger.error(f"Ошибка OCR для блока {block.id}: {e}")
            skipped += 1
    
    logger.info(f"OCR завершён: {processed} блоков обработано, {skipped} пропущено")


def create_ocr_engine(backend: str = "tesseract", **kwargs) -> OCRBackend:
    """
    Фабрика для создания OCR движка
    """
    if backend == "tesseract":
        return TesseractOCRBackend(**kwargs)
    elif backend == "hunyuan":
        return HunyuanOCRBackend(**kwargs)
    elif backend == "dummy":
        return DummyOCRBackend()
    else:
        logger.warning(f"Неизвестный backend '{backend}', используется dummy")
        return DummyOCRBackend()


def run_hunyuan_ocr_full_document(page_images: dict, output_path: str) -> str:
    """
    Распознать весь документ с HunyuanOCR и создать единый Markdown файл
    """
    try:
        logger.info(f"Запуск HunyuanOCR для {len(page_images)} страниц")
        
        # Создаем HunyuanOCR backend
        ocr_engine = HunyuanOCRBackend()
        
        # Собираем результаты по страницам
        markdown_parts = []
        
        for page_num in sorted(page_images.keys()):
            logger.info(f"Обработка страницы {page_num + 1}")
            image = page_images[page_num]
            
            # Распознаем страницу
            # Используем дефолтный промпт для всей страницы
            page_markdown = ocr_engine.recognize(image)
            
            # Добавляем в результат
            markdown_parts.append(f"# Страница {page_num + 1}\n\n{page_markdown}\n\n---\n\n")
        
        # Объединяем в единый документ
        full_markdown = "".join(markdown_parts)
        
        # Сохраняем
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(full_markdown)
        
        logger.info(f"Markdown документ сохранен: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке документа HunyuanOCR: {e}", exc_info=True)
        raise
