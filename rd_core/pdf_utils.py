"""
Утилиты для работы с PDF
Загрузка PDF, рендеринг страниц в изображения через PyMuPDF
"""

import fitz  # PyMuPDF
import logging
from typing import List, Optional
from PIL import Image
import io
from pathlib import Path


# Настройка логирования
logger = logging.getLogger(__name__)

# Увеличиваем лимит PIL для больших изображений (A0 при 300 DPI)
Image.MAX_IMAGE_PIXELS = 500_000_000

# DPI для рендеринга PDF (должен совпадать с сервером)
# Сервер использует PDF_DPI=300, zoom = DPI/72
PDF_RENDER_DPI = 300
PDF_RENDER_ZOOM = PDF_RENDER_DPI / 72.0  # ≈ 4.167


def open_pdf(path: str) -> fitz.Document:
    """
    Открыть PDF-документ
    
    Args:
        path: путь к PDF-файлу
    
    Returns:
        fitz.Document - открытый PDF документ
    
    Raises:
        FileNotFoundError: если файл не найден
        ValueError: если файл не является PDF или повреждён
        Exception: для других ошибок открытия
    """
    pdf_path = Path(path)
    
    # Проверка существования файла
    if not pdf_path.exists():
        logger.error(f"PDF файл не найден: {path}")
        raise FileNotFoundError(f"PDF файл не найден: {path}")
    
    # Проверка расширения
    if pdf_path.suffix.lower() != '.pdf':
        logger.warning(f"Файл не имеет расширения .pdf: {path}")
    
    try:
        doc = fitz.open(path)
        logger.info(f"PDF открыт успешно: {path} (страниц: {len(doc)})")
        return doc
    except fitz.FileDataError as e:
        logger.error(f"Файл не является корректным PDF или повреждён: {path}, ошибка: {e}")
        raise ValueError(f"Файл не является корректным PDF или повреждён: {path}") from e
    except Exception as e:
        logger.error(f"Неожиданная ошибка при открытии PDF {path}: {e}")
        raise


def render_page_to_image(
    doc: fitz.Document, 
    page_index: int, 
    zoom: float = PDF_RENDER_ZOOM
) -> Image.Image:
    """
    Рендеринг страницы PDF в изображение PIL
    
    Args:
        doc: открытый PDF документ
        page_index: индекс страницы (начиная с 0)
        zoom: коэффициент масштабирования (2.0 = 200% = 144 DPI)
              Масштабирование применяется одинаково по X и Y для сохранения пропорций
    
    Returns:
        PIL.Image.Image - отрендеренная страница
    
    Raises:
        IndexError: если page_index выходит за пределы документа
        ValueError: если zoom <= 0
        Exception: для других ошибок рендеринга
    """
    # Валидация zoom
    if zoom <= 0:
        logger.error(f"Некорректный zoom: {zoom}, должен быть > 0")
        raise ValueError(f"Zoom должен быть положительным числом, получено: {zoom}")
    
    # Проверка индекса страницы
    page_count = len(doc)
    if page_index < 0 or page_index >= page_count:
        logger.error(f"Индекс страницы {page_index} выходит за пределы документа (0-{page_count-1})")
        raise IndexError(f"Индекс страницы {page_index} выходит за пределы (доступно: 0-{page_count-1})")
    
    try:
        # Получаем страницу
        page = doc[page_index]
        
        # Адаптивный zoom для больших страниц (лимит ~400 млн пикселей)
        rect = page.rect
        max_pixels = 400_000_000
        estimated_pixels = (rect.width * zoom) * (rect.height * zoom)
        effective_zoom = zoom
        if estimated_pixels > max_pixels:
            effective_zoom = (max_pixels / (rect.width * rect.height)) ** 0.5
            logger.warning(f"Страница {page_index} слишком большая, zoom снижен: {zoom:.2f} -> {effective_zoom:.2f}")
        
        # Создаём матрицу масштабирования (одинаковый zoom по X и Y для сохранения пропорций)
        mat = fitz.Matrix(effective_zoom, effective_zoom)
        
        # Рендерим страницу в pixmap
        pix = page.get_pixmap(matrix=mat)
        
        logger.debug(f"Страница {page_index} отрендерена: {pix.width}x{pix.height}px, zoom={effective_zoom}")
        
        # Конвертация в PIL Image
        # Используем tobytes() для получения сырых данных изображения
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        
        return img
        
    except IndexError:
        # Перебрасываем IndexError дальше
        raise
    except Exception as e:
        logger.error(f"Ошибка рендеринга страницы {page_index}: {e}")
        raise Exception(f"Не удалось отрендерить страницу {page_index}") from e


def render_all_pages(
    doc: fitz.Document, 
    zoom: float = PDF_RENDER_ZOOM
) -> List[Image.Image]:
    """
    Рендеринг всех страниц PDF в изображения PIL
    
    Args:
        doc: открытый PDF документ
        zoom: коэффициент масштабирования (2.0 = 200% = 144 DPI)
              Применяется одинаково ко всем страницам
    
    Returns:
        List[PIL.Image.Image] - список отрендеренных страниц
    
    Raises:
        ValueError: если zoom <= 0 или документ пустой
        Exception: для ошибок рендеринга
    """
    page_count = len(doc)
    
    if page_count == 0:
        logger.warning("PDF документ не содержит страниц")
        raise ValueError("PDF документ пустой (0 страниц)")
    
    if zoom <= 0:
        logger.error(f"Некорректный zoom: {zoom}")
        raise ValueError(f"Zoom должен быть положительным числом, получено: {zoom}")
    
    logger.info(f"Начало рендеринга {page_count} страниц с zoom={zoom}")
    
    images = []
    failed_pages = []
    
    for page_index in range(page_count):
        try:
            img = render_page_to_image(doc, page_index, zoom)
            images.append(img)
            
            # Логируем прогресс каждые 10 страниц или на последней странице
            if (page_index + 1) % 10 == 0 or page_index == page_count - 1:
                logger.info(f"Отрендерено страниц: {page_index + 1}/{page_count}")
                
        except Exception as e:
            logger.error(f"Ошибка при рендеринге страницы {page_index}: {e}")
            failed_pages.append(page_index)
            # Не прерываем процесс, продолжаем со следующей страницей
            # Можно изменить поведение, если нужно строгое исполнение
    
    if failed_pages:
        logger.warning(f"Не удалось отрендерить страницы: {failed_pages}")
        # Если нужно, можно выбросить исключение здесь
        # raise Exception(f"Не удалось отрендерить некоторые страницы: {failed_pages}")
    
    logger.info(f"Рендеринг завершён: {len(images)}/{page_count} страниц успешно")
    
    return images


# ========== КЛАСС-ОБЁРТКА ДЛЯ СОВМЕСТИМОСТИ ==========

class PDFDocument:
    """
    Обёртка над PyMuPDF для работы с PDF-документами
    Использует функции выше для реализации
    """
    
    def __init__(self, pdf_path: str):
        """
        Инициализация PDF-документа
        
        Args:
            pdf_path: путь к PDF-файлу
        """
        self.pdf_path = pdf_path
        self.doc: Optional[fitz.Document] = None
        self.page_count = 0
        
    def open(self) -> bool:
        """
        Открыть PDF-документ
        
        Returns:
            True если успешно открыт, False в случае ошибки
        """
        try:
            self.doc = open_pdf(self.pdf_path)
            self.page_count = len(self.doc)
            return True
        except Exception as e:
            logger.error(f"Не удалось открыть PDF через PDFDocument: {e}")
            return False
    
    def close(self):
        """Закрыть PDF-документ"""
        if self.doc:
            self.doc.close()
            self.doc = None
            logger.debug(f"PDF документ закрыт: {self.pdf_path}")
    
    def render_page(self, page_number: int, zoom: float = PDF_RENDER_ZOOM) -> Optional[Image.Image]:
        """
        Рендеринг страницы в изображение PIL
        
        Args:
            page_number: номер страницы (начиная с 0)
            zoom: коэффициент масштабирования (2.0 = 200% = 144 DPI)
        
        Returns:
            PIL.Image или None в случае ошибки
        """
        if not self.doc or page_number < 0 or page_number >= self.page_count:
            logger.warning(f"Некорректный запрос рендеринга: page={page_number}, doc_opened={self.doc is not None}")
            return None
        
        try:
            return render_page_to_image(self.doc, page_number, zoom)
        except Exception as e:
            logger.error(f"Ошибка рендеринга страницы {page_number}: {e}")
            return None
    
    def render_all(self, zoom: float = PDF_RENDER_ZOOM) -> List[Image.Image]:
        """
        Рендеринг всех страниц документа
        
        Args:
            zoom: коэффициент масштабирования
        
        Returns:
            Список изображений страниц
        """
        if not self.doc:
            logger.warning("Попытка рендеринга всех страниц на закрытом документе")
            return []
        
        try:
            return render_all_pages(self.doc, zoom)
        except Exception as e:
            logger.error(f"Ошибка рендеринга всех страниц: {e}")
            return []
    
    def get_page_dimensions(self, page_number: int, zoom: float = PDF_RENDER_ZOOM) -> Optional[tuple]:
        """
        Получить размеры страницы после рендеринга
        
        Args:
            page_number: номер страницы
            zoom: коэффициент масштабирования
        
        Returns:
            (width, height) или None
        """
        if not self.doc or page_number < 0 or page_number >= self.page_count:
            return None
        
        try:
            page = self.doc[page_number]
            rect = page.rect
            width = int(rect.width * zoom)
            height = int(rect.height * zoom)
            return (width, height)
        except Exception as e:
            logger.error(f"Ошибка получения размеров страницы {page_number}: {e}")
            return None
    
    def __enter__(self):
        """Context manager entry"""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

