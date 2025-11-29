"""
OCR обработка блоков
Абстракция над OCR-движками (сейчас pytesseract, позже Chandra/HunyuanOCR)
"""

import logging
from pathlib import Path
from typing import Protocol, List, Optional
from PIL import Image
import pytesseract
from app.models import Block, BlockType


logger = logging.getLogger(__name__)


class OCRBackend(Protocol):
    """
    Интерфейс для OCR-движков
    """
    
    def recognize(self, image: Image.Image) -> str:
        """
        Распознать текст на изображении
        
        Args:
            image: изображение для распознавания
        
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
    
    def recognize(self, image: Image.Image) -> str:
        """
        Распознать текст через Tesseract
        
        Args:
            image: изображение для распознавания
        
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
    
    def recognize(self, image: Image.Image) -> str:
        """Возвращает заглушку"""
        return "[OCR placeholder - Tesseract not configured]"


def run_ocr_for_blocks(blocks: List[Block], ocr_backend: OCRBackend, base_dir: str = "") -> None:
    """
    Запустить OCR для блоков типа TEXT или TABLE
    
    Args:
        blocks: список блоков для обработки
        ocr_backend: объект, реализующий OCRBackend
        base_dir: базовая директория для поиска файлов (если image_file относительный путь)
    """
    processed = 0
    skipped = 0
    
    for block in blocks:
        # Пропускаем блоки типа IMAGE
        if block.block_type == BlockType.IMAGE:
            logger.debug(f"Блок {block.id} (IMAGE) пропущен - OCR не нужен")
            skipped += 1
            continue
        
        # Пропускаем блоки без image_file
        if not block.image_file:
            logger.warning(f"Блок {block.id} не имеет image_file, пропускаем")
            skipped += 1
            continue
        
        # Проверяем, что тип TEXT или TABLE
        if block.block_type not in (BlockType.TEXT, BlockType.TABLE):
            logger.debug(f"Блок {block.id} имеет тип {block.block_type}, пропускаем")
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
            ocr_text = ocr_backend.recognize(image)
            
            # Сохраняем результат в блок
            block.ocr_text = ocr_text
            processed += 1
            
            logger.debug(f"Блок {block.id}: OCR выполнен ({len(ocr_text)} символов)")
        
        except Exception as e:
            logger.error(f"Ошибка OCR для блока {block.id}: {e}")
            skipped += 1
    
    logger.info(f"OCR завершён: {processed} блоков обработано, {skipped} пропущено")


def create_ocr_engine(backend: str = "tesseract", **kwargs) -> OCRBackend:
    """
    Фабрика для создания OCR движка
    
    Args:
        backend: тип движка ("tesseract", "dummy")
        **kwargs: параметры для движка
    
    Returns:
        OCRBackend объект
    """
    if backend == "tesseract":
        return TesseractOCRBackend(**kwargs)
    elif backend == "dummy":
        return DummyOCRBackend()
    else:
        logger.warning(f"Неизвестный backend '{backend}', используется dummy")
        return DummyOCRBackend()

