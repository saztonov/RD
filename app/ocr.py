"""
OCR обработка блоков
Абстракция над OCR-движками (сейчас pytesseract, позже Chandra/HunyuanOCR)
"""

import logging
from PIL import Image
from typing import Optional
import pytesseract


logger = logging.getLogger(__name__)


class OCREngine:
    """
    Абстрактный класс для OCR-движков
    """
    
    def recognize(self, image: Image.Image) -> str:
        """
        Распознать текст на изображении
        
        Args:
            image: изображение для распознавания
        
        Returns:
            Распознанный текст
        """
        raise NotImplementedError


class TesseractOCR(OCREngine):
    """
    OCR через Tesseract (pytesseract)
    
    Требует установленного Tesseract:
    - Windows: скачать с https://github.com/UB-Mannheim/tesseract/wiki
    - Указать путь: pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
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
        
        logger.info(f"TesseractOCR инициализирован (языки: {lang})")
    
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
        except pytesseract.TesseractNotFoundError as e:
            logger.error(f"Tesseract не найден. Установите Tesseract и укажите путь: {e}")
            return ""
        except Exception as e:
            logger.error(f"Ошибка OCR: {e}")
            return ""


class DummyOCR(OCREngine):
    """
    Заглушка для OCR (для тестирования без Tesseract)
    """
    
    def recognize(self, image: Image.Image) -> str:
        """Возвращает заглушку"""
        return "[OCR placeholder - Tesseract not configured]"


# Фабрика OCR-движков
def create_ocr_engine(engine_type: str = "tesseract", **kwargs) -> OCREngine:
    """
    Создать OCR-движок
    
    Args:
        engine_type: тип движка ('tesseract', 'dummy', позже 'chandra', 'hunyuan')
        **kwargs: параметры для конкретного движка
    
    Returns:
        Экземпляр OCR-движка
    """
    if engine_type == "tesseract":
        return TesseractOCR(**kwargs)
    elif engine_type == "dummy":
        return DummyOCR()
    else:
        raise ValueError(f"Неизвестный тип OCR-движка: {engine_type}")

