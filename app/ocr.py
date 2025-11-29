"""
OCR обработка блоков
Абстракция над OCR-движками (pytesseract, HunyuanOCR)
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


class HunyuanOCRBackend:
    """
    OCR через HunyuanOCR (Tencent VLM)
    Поддержка многоязычных документов с таблицами и формулами
    
    Требует установки репозитория:
    git clone https://github.com/Tencent-Hunyuan/HunyuanOCR.git
    cd HunyuanOCR/Hunyuan-OCR-master
    pip install -r requirements.txt
    """
    
    def __init__(self, hunyuan_repo_path: Optional[str] = None):
        """
        Args:
            hunyuan_repo_path: путь к клонированному репозиторию HunyuanOCR
                               (по умолчанию ищет в ./HunyuanOCR или ./Новая папка/HunyuanOCR)
        """
        try:
            import sys
            from pathlib import Path as PathLib
            
            # Ищем репозиторий HunyuanOCR
            if hunyuan_repo_path:
                repo_path = PathLib(hunyuan_repo_path)
            else:
                # Пробуем стандартные пути
                possible_paths = [
                    PathLib("HunyuanOCR/Hunyuan-OCR-master"),
                    PathLib("Новая папка/HunyuanOCR/Hunyuan-OCR-master"),
                    PathLib("../HunyuanOCR/Hunyuan-OCR-master"),
                ]
                repo_path = None
                for path in possible_paths:
                    if path.exists():
                        repo_path = path
                        break
                
                if not repo_path:
                    raise FileNotFoundError(
                        "Репозиторий HunyuanOCR не найден. Установите его:\n"
                        "git clone https://github.com/Tencent-Hunyuan/HunyuanOCR.git\n"
                        "cd HunyuanOCR/Hunyuan-OCR-master\n"
                        "pip install -r requirements.txt"
                    )
            
            # Добавляем путь в sys.path
            sys.path.insert(0, str(repo_path))
            logger.info(f"HunyuanOCR репозиторий найден: {repo_path}")
            
            # Импортируем HunyuanOCR
            try:
                from inference import HunyuanOCR
                self.ocr_model = HunyuanOCR()
                logger.info("HunyuanOCR инициализирован успешно")
            except ImportError as e:
                logger.error(f"Не удалось импортировать HunyuanOCR: {e}")
                raise ImportError(
                    f"Ошибка импорта HunyuanOCR из {repo_path}. "
                    "Убедитесь что установлены зависимости: pip install -r requirements.txt"
                )
            
            # Промпт для извлечения документа в Markdown
            self.prompt = (
                "Извлеките всю информацию из основного текста изображения документа "
                "и представьте ее в формате Markdown, игнорируя заголовки и колонтитулы. "
                "Таблицы должны быть выражены в формате HTML, формулы — в формате LaTeX, "
                "а разбор должен быть организован в соответствии с порядком чтения."
            )
            
        except Exception as e:
            logger.error(f"Ошибка инициализации HunyuanOCR: {e}")
            raise
    
    def recognize(self, image: Image.Image) -> str:
        """
        Распознать текст через HunyuanOCR
        
        Args:
            image: изображение для распознавания
        
        Returns:
            Распознанный текст в Markdown формате
        """
        try:
            # Вызываем HunyuanOCR с промптом
            result = self.ocr_model.predict(image, prompt=self.prompt)
            
            logger.debug(f"HunyuanOCR: распознано {len(result)} символов")
            return result.strip()
            
        except Exception as e:
            logger.error(f"Ошибка HunyuanOCR распознавания: {e}")
            return f"[Ошибка HunyuanOCR: {e}]"


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
        backend: тип движка ("tesseract", "dummy", "hunyuan")
        **kwargs: параметры для движка
    
    Returns:
        OCRBackend объект
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
    
    Args:
        page_images: словарь {page_num: PIL.Image} со всеми страницами
        output_path: путь для сохранения результирующего MD файла
    
    Returns:
        Путь к созданному MD файлу
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

