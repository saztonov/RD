"""
Пример использования Chandra OCR для распознавания документов
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ocr import ChandraOCRBackend, run_chandra_ocr_full_document
from app.pdf_utils import PDFDocument
from PIL import Image


def test_single_image():
    """Тест распознавания одного изображения"""
    print("=" * 60)
    print("Тест 1: Распознавание одного изображения")
    print("=" * 60)
    
    # Загружаем изображение
    image_path = "test_page.png"
    if not Path(image_path).exists():
        print(f"Файл {image_path} не найден. Пропускаем тест.")
        return
    
    image = Image.open(image_path)
    
    # Создаем OCR движок
    print("Инициализация Chandra OCR (метод: hf)...")
    ocr = ChandraOCRBackend(method="hf")
    
    # Распознаем
    print("Распознавание...")
    result = ocr.recognize(image)
    
    print("\nРезультат:")
    print("-" * 60)
    print(result)
    print("-" * 60)
    
    # Сохраняем результат
    with open("test_result.md", "w", encoding="utf-8") as f:
        f.write(result)
    
    print("\nРезультат сохранен в test_result.md")


def test_full_pdf():
    """Тест распознавания всего PDF документа"""
    print("\n" + "=" * 60)
    print("Тест 2: Распознавание PDF документа")
    print("=" * 60)
    
    # Путь к тестовому PDF
    pdf_path = "test_document.pdf"
    if not Path(pdf_path).exists():
        print(f"Файл {pdf_path} не найден. Пропускаем тест.")
        return
    
    # Открываем PDF
    print(f"Открываем {pdf_path}...")
    pdf_doc = PDFDocument(pdf_path)
    if not pdf_doc.open():
        print("Ошибка открытия PDF")
        return
    
    # Рендерим все страницы
    print(f"Рендерим {pdf_doc.page_count} страниц...")
    page_images = {}
    for page_num in range(pdf_doc.page_count):
        img = pdf_doc.render_page(page_num)
        if img:
            page_images[page_num] = img
        print(f"  Страница {page_num + 1}/{pdf_doc.page_count}")
    
    # Запускаем распознавание
    print("\nЗапуск Chandra OCR для всего документа...")
    output_path = "test_full_document.md"
    result_path = run_chandra_ocr_full_document(page_images, output_path, method="hf")
    
    print(f"\n✅ Документ распознан и сохранен: {result_path}")
    
    # Закрываем PDF
    pdf_doc.close()


def main():
    """Главная функция"""
    try:
        # Тест 1: одно изображение
        test_single_image()
        
        # Тест 2: полный документ
        test_full_pdf()
        
        print("\n" + "=" * 60)
        print("✅ Все тесты завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

