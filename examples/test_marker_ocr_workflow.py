"""
Пример использования Marker разметки с последующим OCR по типам блоков
"""

from pathlib import Path
from app.pdf_utils import PDFDocument
from app.models import Page, BlockType
from app.marker_integration import segment_with_marker
from app.ocr import create_ocr_engine, generate_structured_markdown
from PIL import Image


def test_marker_ocr_workflow():
    """
    Демонстрация полного workflow:
    1. Загрузка PDF
    2. Marker разметка
    3. OCR с учетом типов блоков
    4. Генерация структурированного Markdown
    """
    
    # Путь к тестовому PDF
    pdf_path = "test_document.pdf"
    
    if not Path(pdf_path).exists():
        print(f"PDF файл не найден: {pdf_path}")
        return
    
    print("=" * 60)
    print("MARKER + OCR WORKFLOW")
    print("=" * 60)
    
    # 1. Открытие PDF
    print("\n1. Открытие PDF...")
    pdf_doc = PDFDocument(pdf_path)
    print(f"   Страниц: {pdf_doc.page_count}")
    
    # 2. Создание страниц для разметки
    print("\n2. Подготовка страниц...")
    pages = []
    page_images = {}
    
    for page_num in range(pdf_doc.page_count):
        # Рендерим страницу
        img = pdf_doc.render_page(page_num)
        if img:
            page_images[page_num] = img
            
            # Создаем Page объект
            page = Page(
                page_number=page_num,
                width=img.width,
                height=img.height,
                blocks=[]
            )
            pages.append(page)
    
    print(f"   Отрендерено {len(page_images)} страниц")
    
    # 3. Marker разметка
    print("\n3. Запуск Marker разметки...")
    try:
        updated_pages = segment_with_marker(
            pdf_path,
            pages,
            page_images=page_images,
            page_range=None,  # Все страницы
            category="Marker"
        )
        
        if updated_pages:
            pages = updated_pages
            
            # Статистика блоков
            total_blocks = sum(len(p.blocks) for p in pages)
            text_blocks = sum(len([b for b in p.blocks if b.block_type == BlockType.TEXT]) for p in pages)
            table_blocks = sum(len([b for b in p.blocks if b.block_type == BlockType.TABLE]) for p in pages)
            image_blocks = sum(len([b for b in p.blocks if b.block_type == BlockType.IMAGE]) for p in pages)
            
            print(f"   Найдено блоков: {total_blocks}")
            print(f"   - TEXT: {text_blocks}")
            print(f"   - TABLE: {table_blocks}")
            print(f"   - IMAGE: {image_blocks}")
        else:
            print("   ❌ Ошибка разметки")
            return
            
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return
    
    # 4. Создание кропов для OCR
    print("\n4. Создание кропов блоков...")
    crops_dir = Path("temp_crops")
    crops_dir.mkdir(exist_ok=True)
    
    for page in pages:
        page_num = page.page_number
        page_img = page_images.get(page_num)
        
        if not page_img:
            continue
        
        for block in page.blocks:
            x1, y1, x2, y2 = block.coords_px
            if x1 < x2 and y1 < y2:
                crop = page_img.crop((x1, y1, x2, y2))
                crop_filename = f"page{page_num}_block{block.id}.png"
                crop_path = crops_dir / crop_filename
                crop.save(crop_path, "PNG")
                block.image_file = str(crop_path)
    
    print(f"   Кропы сохранены в {crops_dir}")
    
    # 5. OCR с учетом типов
    print("\n5. Запуск OCR по типам блоков...")
    
    # Создаем движки
    try:
        # Для TEXT/TABLE используем Chandra (или VLM)
        text_engine = create_ocr_engine("local_vlm", 
                                       api_base="http://127.0.0.1:1234/v1",
                                       model_name="qwen3-vl-32b-instruct")
        
        # Для IMAGE используем VLM с специальным промптом
        image_engine = create_ocr_engine("local_vlm",
                                        api_base="http://127.0.0.1:1234/v1",
                                        model_name="qwen3-vl-32b-instruct")
        
        print("   ✓ OCR движки инициализированы")
        
    except Exception as e:
        print(f"   ❌ Ошибка инициализации OCR: {e}")
        return
    
    # Обрабатываем блоки
    for page in pages:
        page_num = page.page_number
        print(f"\n   Страница {page_num + 1}...")
        
        for block in page.blocks:
            if not block.image_file or not Path(block.image_file).exists():
                continue
            
            try:
                crop = Image.open(block.image_file)
                
                if block.block_type == BlockType.IMAGE:
                    # Детальное описание изображения из промпта
                    from app.ocr import load_prompt
                    image_prompt = load_prompt("ocr_image_description.txt")
                    if image_prompt:
                        block.ocr_text = image_engine.recognize(crop, prompt=image_prompt)
                    else:
                        # Fallback
                        block.ocr_text = image_engine.recognize(crop)
                    print(f"     ✓ IMAGE блок {block.id[:8]}... описан")
                    
                elif block.block_type == BlockType.TABLE:
                    # Таблица с промптом
                    from app.ocr import load_prompt
                    table_prompt = load_prompt("ocr_table.txt")
                    if table_prompt:
                        block.ocr_text = text_engine.recognize(crop, prompt=table_prompt)
                    else:
                        block.ocr_text = text_engine.recognize(crop)
                    print(f"     ✓ TABLE блок {block.id[:8]}... распознан")
                    
                elif block.block_type == BlockType.TEXT:
                    # Текст с промптом
                    from app.ocr import load_prompt
                    text_prompt = load_prompt("ocr_text.txt")
                    if text_prompt:
                        block.ocr_text = text_engine.recognize(crop, prompt=text_prompt)
                    else:
                        block.ocr_text = text_engine.recognize(crop)
                    print(f"     ✓ TEXT блок {block.id[:8]}... распознан")
                    
            except Exception as e:
                print(f"     ❌ Ошибка блока {block.id[:8]}: {e}")
                block.ocr_text = f"[Error: {e}]"
    
    # 6. Генерация структурированного Markdown
    print("\n6. Генерация Markdown документа...")
    output_path = "recognized_structured_document.md"
    
    try:
        result_path = generate_structured_markdown(
            pages,
            output_path,
            images_dir="temp_crops"
        )
        
        print(f"   ✓ Markdown сохранен: {result_path}")
        
        # Статистика
        processed_blocks = sum(1 for p in pages for b in p.blocks if b.ocr_text)
        print(f"\n   Обработано блоков: {processed_blocks}")
        
    except Exception as e:
        print(f"   ❌ Ошибка генерации: {e}")
        return
    
    print("\n" + "=" * 60)
    print("WORKFLOW ЗАВЕРШЕН")
    print("=" * 60)
    print(f"\nРезультаты:")
    print(f"  - Markdown: {output_path}")
    print(f"  - Кропы изображений: {crops_dir}/")
    print(f"\nОткройте {output_path} для просмотра структурированного документа")
    print("с описаниями изображений на русском языке!")


if __name__ == "__main__":
    test_marker_ocr_workflow()

