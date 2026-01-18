# rd_domain

**Layer 0** — Доменный слой без внешних зависимостей.

Содержит доменные модели, идентификаторы и схемы аннотаций. Зависит только от стандартной библиотеки Python.

## Модули

### ids/
OCR-устойчивые идентификаторы блоков.

```python
from rd_domain import (
    generate_armor_id, is_armor_id, ArmorID,
    uuid_to_armor_id, migrate_block_id,
    encode_block_id, decode_armor_code, match_armor_to_uuid
)

# Генерация нового ID
block_id = generate_armor_id()  # "34GH-KLMN-PQR"

# Проверка формата
is_armor_id("34GH-KLMN-PQR")  # True

# Конвертация UUID в ArmorID
armor = uuid_to_armor_id("550e8400-e29b-41d4-a716-446655440000")

# Миграция старого ID в новый формат
new_id, was_migrated = migrate_block_id("old-uuid-format")

# Восстановление повреждённого кода (до 3 ошибок)
success, fixed, msg = ArmorID.repair("34GH-KLMN-P0R")
```

**Формат ArmorID:** `XXXX-XXXX-XXX`
- 8 символов payload (40 бит энтропии)
- 3 символа checksum
- Алфавит: `34679ACDEFGHJKLMNPQRTUVWXY` (26 символов без визуально похожих)

### models/
Доменные модели данных.

```python
from rd_domain import Block, BlockType, BlockSource, ShapeType

# Создание блока
block = Block.create(
    page_index=0,
    coords_px=(100, 200, 300, 400),
    page_width=1000,
    page_height=1500,
    block_type=BlockType.TEXT,
    source=BlockSource.USER,
)

# Сериализация
data = block.to_dict()

# Десериализация
block, was_migrated = Block.from_dict(data)
```

**Block** — единица аннотации PDF:
- `id` — ArmorID
- `page_index` — индекс страницы (с 0)
- `coords_px` — пиксельные координаты (x1, y1, x2, y2)
- `coords_norm` — нормализованные координаты (0..1)
- `block_type` — TEXT или IMAGE
- `source` — USER или AUTO
- `shape_type` — RECTANGLE или POLYGON
- `ocr_text` — результат OCR

**Document** — коллекция страниц.

**Page** — страница с блоками.

### annotation/
Чтение/запись аннотаций.

```python
from rd_domain.annotation import load_blocks_file, save_blocks_file

# Загрузка
blocks, was_migrated = load_blocks_file("blocks.json")

# Сохранение
save_blocks_file(blocks, "blocks.json")
```

### manifest/
Модели манифеста для two-pass OCR.

### utils/
Утилиты (datetime).

```python
from rd_domain import get_moscow_time_str

timestamp = get_moscow_time_str()  # "2024-01-01T12:00:00+03:00"
```

## Типы и перечисления

```python
from rd_domain import BlockType, BlockSource, ShapeType

BlockType.TEXT      # Текстовый блок
BlockType.IMAGE     # Изображение

BlockSource.USER    # Создан пользователем
BlockSource.AUTO    # Автоматическая сегментация

ShapeType.RECTANGLE # Прямоугольник
ShapeType.POLYGON   # Произвольный полигон
```

## Правила импорта

rd_domain — нижний слой архитектуры:
- Зависит только от stdlib Python
- НЕ импортирует из `rd_pipeline`, `rd_adapters`, `apps/`
- Может импортироваться всеми остальными слоями

```
rd_domain (Layer 0)
    ↑
rd_pipeline (Layer 1)
    ↑
rd_adapters (Layer 2)
    ↑
apps/ (Application Layer)
```
