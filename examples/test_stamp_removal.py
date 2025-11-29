"""
Тестирование функционала удаления штампов
"""

import sys
from pathlib import Path

# Добавляем корневую папку в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.pdf_structure import PDFStructureAnalyzer, PDFStructureModifier, PDFElementType


def test_analyze_structure(pdf_path: str):
    """Тестирование анализа структуры PDF"""
    print(f"\n=== Анализ структуры PDF ===")
    print(f"Файл: {pdf_path}\n")
    
    analyzer = PDFStructureAnalyzer(pdf_path)
    
    if not analyzer.open():
        print("❌ Не удалось открыть PDF")
        return
    
    # Анализируем все страницы
    page_elements = analyzer.analyze_all_pages()
    
    total_annotations = 0
    total_images = 0
    total_forms = 0
    
    for page_num, elements in page_elements.items():
        print(f"Страница {page_num + 1}:")
        
        for elem in elements:
            if elem.element_type == PDFElementType.ANNOTATION:
                total_annotations += 1
                print(f"  📌 {elem.name}")
            elif elem.element_type == PDFElementType.IMAGE:
                total_images += 1
                print(f"  🖼️ {elem.name}")
            elif elem.element_type == PDFElementType.FORM:
                total_forms += 1
                print(f"  📦 {elem.name}")
        
        print()
    
    print(f"Всего:")
    print(f"  Аннотаций: {total_annotations}")
    print(f"  Изображений: {total_images}")
    print(f"  Контейнеров: {total_forms}")
    
    analyzer.close()


def test_remove_elements(pdf_path: str, output_path: str):
    """Тестирование удаления элементов"""
    print(f"\n=== Удаление элементов ===")
    print(f"Вход: {pdf_path}")
    print(f"Выход: {output_path}\n")
    
    # Анализируем
    analyzer = PDFStructureAnalyzer(pdf_path)
    if not analyzer.open():
        print("❌ Не удалось открыть PDF")
        return
    
    page_elements = analyzer.analyze_all_pages()
    analyzer.close()
    
    # Собираем все аннотации для удаления
    to_remove = []
    for elements in page_elements.values():
        for elem in elements:
            if elem.element_type == PDFElementType.ANNOTATION:
                to_remove.append(elem)
    
    print(f"Найдено аннотаций для удаления: {len(to_remove)}")
    
    # Удаляем
    modifier = PDFStructureModifier(pdf_path)
    if not modifier.open():
        print("❌ Не удалось открыть PDF для модификации")
        return
    
    removed_count = modifier.remove_elements(to_remove)
    print(f"Удалено: {removed_count}")
    
    # Сохраняем
    if modifier.save(output_path):
        print(f"✅ Сохранено: {output_path}")
    else:
        print("❌ Не удалось сохранить")
    
    modifier.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование:")
        print(f"  python {sys.argv[0]} <pdf_file>")
        print(f"  python {sys.argv[0]} <pdf_file> <output_file>")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    
    if not Path(pdf_file).exists():
        print(f"❌ Файл не найден: {pdf_file}")
        sys.exit(1)
    
    # Анализ
    test_analyze_structure(pdf_file)
    
    # Удаление (если указан выходной файл)
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
        test_remove_elements(pdf_file, output_file)

