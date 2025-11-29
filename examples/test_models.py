"""
Примеры использования обновлённых моделей данных
"""

import sys
from pathlib import Path

# Добавляем родительскую директорию в path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models import (
    Block, BlockType, BlockSource, PageModel,
    create_block_from_legacy, block_to_legacy_coords,
    coords_xywh_to_xyxy, coords_xyxy_to_xywh
)
from PIL import Image
import json


def example_1_create_block():
    """Пример 1: Создание блока с координатами"""
    print("=== Пример 1: Создание блока ===")
    
    # Параметры страницы
    page_width = 1600
    page_height = 2400
    
    # Создаём блок с координатами в пикселях
    block = Block.create(
        page_index=0,
        coords_px=(100, 200, 500, 400),  # x1, y1, x2, y2
        page_width=page_width,
        page_height=page_height,
        category="Заголовок",
        block_type=BlockType.TEXT,
        source=BlockSource.USER
    )
    
    print(f"Block ID: {block.id}")
    print(f"Координаты (px): {block.coords_px}")
    print(f"Координаты (norm): {block.coords_norm}")
    print(f"Размеры (px): {block.get_width_height_px()}")
    print(f"Тип: {block.block_type.value}")
    print(f"Источник: {block.source.value}")
    print()


def example_2_coordinate_conversion():
    """Пример 2: Конвертация координат"""
    print("=== Пример 2: Конвертация координат ===")
    
    page_width = 1600
    page_height = 2400
    
    # Координаты в пикселях
    coords_px = (100, 200, 500, 600)
    print(f"Исходные координаты (px): {coords_px}")
    
    # Конвертация px → norm
    coords_norm = Block.px_to_norm(coords_px, page_width, page_height)
    print(f"Нормализованные: {coords_norm}")
    
    # Конвертация norm → px (обратно)
    coords_px_back = Block.norm_to_px(coords_norm, page_width, page_height)
    print(f"Обратно в px: {coords_px_back}")
    print()


def example_3_legacy_conversion():
    """Пример 3: Конвертация из legacy формата"""
    print("=== Пример 3: Конвертация из legacy формата ===")
    
    # Legacy формат: x, y, width, height
    x, y, width, height = 100, 200, 400, 200
    page_width = 1600
    page_height = 2400
    
    print(f"Legacy координаты: x={x}, y={y}, w={width}, h={height}")
    
    # Создаём новый блок из legacy формата
    block = create_block_from_legacy(
        x=x, y=y, width=width, height=height,
        page_index=0,
        page_width=page_width,
        page_height=page_height,
        block_type=BlockType.TABLE,
        is_auto=True,
        description="Таблица параметров"
    )
    
    print(f"Новый формат (x1,y1,x2,y2): {block.coords_px}")
    print(f"Category: {block.category}")
    print(f"Source: {block.source.value}")
    
    # Конвертация обратно в legacy
    legacy_coords = block_to_legacy_coords(block)
    print(f"Обратно в legacy: x={legacy_coords[0]}, y={legacy_coords[1]}, "
          f"w={legacy_coords[2]}, h={legacy_coords[3]}")
    print()


def example_4_page_model():
    """Пример 4: Работа с PageModel"""
    print("=== Пример 4: Работа с PageModel ===")
    
    # Создаём тестовое изображение
    test_image = Image.new('RGB', (1600, 2400), color='white')
    
    # Создаём модель страницы
    page = PageModel(
        page_index=0,
        image=test_image
    )
    
    print(f"Страница {page.page_index}")
    print(f"Размер: {page.width}x{page.height}")
    
    # Добавляем блоки
    block1 = Block.create(
        page_index=0,
        coords_px=(100, 100, 500, 200),
        page_width=page.width,
        page_height=page.height,
        category="Заголовок",
        block_type=BlockType.TEXT,
        source=BlockSource.USER
    )
    
    block2 = Block.create(
        page_index=0,
        coords_px=(100, 300, 700, 800),
        page_width=page.width,
        page_height=page.height,
        category="Таблица данных",
        block_type=BlockType.TABLE,
        source=BlockSource.AUTO
    )
    
    page.add_block(block1)
    page.add_block(block2)
    
    print(f"Всего блоков: {len(page.blocks)}")
    
    # Фильтрация по типу
    text_blocks = page.get_blocks_by_type(BlockType.TEXT)
    print(f"Текстовых блоков: {len(text_blocks)}")
    
    # Фильтрация по источнику
    auto_blocks = page.get_blocks_by_source(BlockSource.AUTO)
    print(f"Автоматических блоков: {len(auto_blocks)}")
    
    # Поиск по ID
    found_block = page.get_block_by_id(block1.id)
    if found_block:
        print(f"Найден блок: {found_block.category}")
    print()


def example_5_serialization():
    """Пример 5: Сериализация в JSON"""
    print("=== Пример 5: Сериализация в JSON ===")
    
    # Создаём блок
    block = Block.create(
        page_index=0,
        coords_px=(100, 200, 500, 600),
        page_width=1600,
        page_height=2400,
        category="Пример блока",
        block_type=BlockType.TEXT,
        source=BlockSource.USER,
        ocr_text="Распознанный текст"
    )
    
    # Сериализация в dict
    block_dict = block.to_dict()
    print("Сериализованный блок:")
    print(json.dumps(block_dict, indent=2, ensure_ascii=False))
    
    # Десериализация обратно
    restored_block = Block.from_dict(block_dict)
    print(f"\nВосстановленный блок ID: {restored_block.id}")
    print(f"Category: {restored_block.category}")
    print(f"OCR: {restored_block.ocr_text}")
    print()


def example_6_update_coordinates():
    """Пример 6: Обновление координат блока"""
    print("=== Пример 6: Обновление координат ===")
    
    page_width = 1600
    page_height = 2400
    
    # Создаём блок
    block = Block.create(
        page_index=0,
        coords_px=(100, 200, 500, 600),
        page_width=page_width,
        page_height=page_height,
        category="Блок",
        block_type=BlockType.TEXT,
        source=BlockSource.USER
    )
    
    print(f"Исходные координаты (px): {block.coords_px}")
    print(f"Исходные координаты (norm): {block.coords_norm}")
    
    # Изменяем размер страницы (например, другой zoom)
    new_page_width = 3200  # 2x zoom
    new_page_height = 4800
    
    # Пересчитываем координаты из нормализованных в новый размер
    new_coords_px = Block.norm_to_px(
        block.coords_norm,
        new_page_width,
        new_page_height
    )
    
    print(f"\nНовые координаты для 2x страницы: {new_coords_px}")
    print(f"Нормализованные (не изменились): {block.coords_norm}")
    
    # Обновляем блок
    block.update_coords_px(new_coords_px, new_page_width, new_page_height)
    print(f"Блок обновлён: {block.coords_px}")
    print()


def example_7_coord_format_helpers():
    """Пример 7: Helper функции для форматов координат"""
    print("=== Пример 7: Helper функции ===")
    
    # Формат (x, y, width, height)
    x, y, w, h = 100, 200, 400, 300
    print(f"Формат (x,y,w,h): {x}, {y}, {w}, {h}")
    
    # Конвертация в (x1, y1, x2, y2)
    x1, y1, x2, y2 = coords_xywh_to_xyxy(x, y, w, h)
    print(f"Формат (x1,y1,x2,y2): {x1}, {y1}, {x2}, {y2}")
    
    # Конвертация обратно
    x_back, y_back, w_back, h_back = coords_xyxy_to_xywh(x1, y1, x2, y2)
    print(f"Обратно в (x,y,w,h): {x_back}, {y_back}, {w_back}, {h_back}")
    print()


if __name__ == "__main__":
    print("Тестирование обновлённых моделей данных\n")
    
    example_1_create_block()
    example_2_coordinate_conversion()
    example_3_legacy_conversion()
    example_4_page_model()
    example_5_serialization()
    example_6_update_coordinates()
    example_7_coord_format_helpers()
    
    print("✓ Все примеры выполнены успешно!")

