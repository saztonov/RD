"""
Пример использования функций рендеринга PDF
"""

import logging
import sys
from pathlib import Path

# Добавляем родительскую директорию в path для импорта модулей app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.pdf_utils import open_pdf, render_page_to_image, render_all_pages


# Настройка логирования для примера
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def example_render_single_page(pdf_path: str, page_index: int = 0):
    """Пример: рендеринг одной страницы"""
    logger.info("=== Пример 1: Рендеринг одной страницы ===")
    
    try:
        # Открываем PDF
        doc = open_pdf(pdf_path)
        
        # Рендерим первую страницу
        image = render_page_to_image(doc, page_index, zoom=2.0)
        
        logger.info(f"Страница {page_index} отрендерена: {image.size} (ширина x высота)")
        
        # Сохраняем для проверки
        output_path = f"page_{page_index}.png"
        image.save(output_path)
        logger.info(f"Изображение сохранено: {output_path}")
        
        # Закрываем документ
        doc.close()
        
    except FileNotFoundError as e:
        logger.error(f"Файл не найден: {e}")
    except ValueError as e:
        logger.error(f"Ошибка валидации: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")


def example_render_all_pages(pdf_path: str):
    """Пример: рендеринг всех страниц"""
    logger.info("=== Пример 2: Рендеринг всех страниц ===")
    
    try:
        # Открываем PDF
        doc = open_pdf(pdf_path)
        
        # Рендерим все страницы
        images = render_all_pages(doc, zoom=1.5)
        
        logger.info(f"Всего отрендерено страниц: {len(images)}")
        
        # Сохраняем все страницы
        for idx, image in enumerate(images):
            output_path = f"all_pages/page_{idx + 1}.png"
            Path(output_path).parent.mkdir(exist_ok=True)
            image.save(output_path)
            logger.info(f"Сохранена страница {idx + 1}: {image.size}")
        
        # Закрываем документ
        doc.close()
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")


def example_with_different_zooms(pdf_path: str):
    """Пример: рендеринг с разными уровнями zoom"""
    logger.info("=== Пример 3: Разные уровни масштабирования ===")
    
    try:
        doc = open_pdf(pdf_path)
        
        zooms = [1.0, 1.5, 2.0, 3.0]
        
        for zoom in zooms:
            image = render_page_to_image(doc, 0, zoom=zoom)
            output_path = f"zoom_comparison/page_0_zoom_{zoom}.png"
            Path(output_path).parent.mkdir(exist_ok=True)
            image.save(output_path)
            logger.info(f"Zoom {zoom}: размер {image.size}, файл: {output_path}")
        
        doc.close()
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")


def example_error_handling():
    """Пример: обработка ошибок"""
    logger.info("=== Пример 4: Обработка ошибок ===")
    
    # Несуществующий файл
    try:
        doc = open_pdf("nonexistent.pdf")
    except FileNotFoundError as e:
        logger.info(f"✓ Корректно обработан: {e}")
    
    # Некорректный индекс страницы
    try:
        doc = open_pdf("test.pdf")  # Укажите реальный файл
        image = render_page_to_image(doc, 9999)
    except IndexError as e:
        logger.info(f"✓ Корректно обработан: {e}")
    except FileNotFoundError:
        logger.info("✓ test.pdf не найден (для теста нужен реальный файл)")
    
    # Некорректный zoom
    try:
        doc = open_pdf("test.pdf")
        image = render_page_to_image(doc, 0, zoom=-1.0)
    except ValueError as e:
        logger.info(f"✓ Корректно обработан: {e}")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    # Укажите путь к вашему PDF файлу
    PDF_PATH = "sample.pdf"  # Замените на реальный путь
    
    if len(sys.argv) > 1:
        PDF_PATH = sys.argv[1]
    
    logger.info(f"Тестирование с файлом: {PDF_PATH}")
    
    # Раскомментируйте нужный пример:
    
    # example_render_single_page(PDF_PATH, page_index=0)
    # example_render_all_pages(PDF_PATH)
    # example_with_different_zooms(PDF_PATH)
    example_error_handling()
    
    logger.info("Готово!")

