# 📦 Модель данных приложения

## Обзор

Модуль `app/models.py` содержит обновлённую модель данных для представления PDF-документов, страниц и блоков разметки с поддержкой:
- Двух систем координат (пиксели и нормализованные)
- Уникальных идентификаторов блоков
- Категоризации и типизации блоков
- Источника создания (вручную/автоматически)
- Интеграции с PIL.Image

---

## 🔢 Enums

### `BlockType`

Типы блоков разметки:

```python
class BlockType(Enum):
    TEXT = "text"    # Текстовый блок
    TABLE = "table"  # Таблица
    IMAGE = "image"  # Изображение
```

### `BlockSource`

Источник создания блока:

```python
class BlockSource(Enum):
    USER = "user"  # Создан пользователем вручную
    AUTO = "auto"  # Создан автоматической сегментацией
```

---

## 📍 Класс `Block`

Блок разметки на странице PDF с двумя системами координат.

### Атрибуты

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | `str` | Уникальный идентификатор (UUID) |
| `page_index` | `int` | Индекс страницы (начиная с 0) |
| `coords_px` | `Tuple[int, int, int, int]` | Координаты в пикселях (x1, y1, x2, y2) |
| `coords_norm` | `Tuple[float, float, float, float]` | Нормализованные координаты 0..1 (x1, y1, x2, y2) |
| `category` | `str` | Описание/группа блока (например, "Заголовок", "Параметры") |
| `block_type` | `BlockType` | Тип блока (TEXT/TABLE/IMAGE) |
| `source` | `BlockSource` | Источник создания (USER/AUTO) |
| `image_file` | `Optional[str]` | Путь к сохранённому кропу блока |
| `ocr_text` | `Optional[str]` | Результат OCR распознавания |

### Системы координат

**Координаты в пикселях (coords_px):**
- Абсолютные координаты на отрендеренном изображении
- Формат: `(x1, y1, x2, y2)` где (x1, y1) — верхний левый угол, (x2, y2) — нижний правый
- Зависят от размера изображения и zoom при рендеринге

**Нормализованные координаты (coords_norm):**
- Относительные координаты в диапазоне 0..1
- x нормализован к ширине страницы, y — к высоте
- Не зависят от zoom, позволяют переносить разметку между версиями PDF

### Создание блока

```python
from app.models import Block, BlockType, BlockSource

# Способ 1: Прямое создание с автоматическим вычислением norm координат
block = Block.create(
    page_index=0,
    coords_px=(100, 200, 500, 600),  # x1, y1, x2, y2
    page_width=1600,
    page_height=2400,
    category="Заголовок",
    block_type=BlockType.TEXT,
    source=BlockSource.USER,
    ocr_text="Распознанный текст"  # опционально
)

# Способ 2: Ручное создание (если уже есть norm координаты)
block = Block(
    id="custom-id-123",  # или Block.generate_id()
    page_index=0,
    coords_px=(100, 200, 500, 600),
    coords_norm=(0.0625, 0.0833, 0.3125, 0.25),
    category="Заголовок",
    block_type=BlockType.TEXT,
    source=BlockSource.USER
)
```

### Статические методы

#### `generate_id() -> str`

Генерирует уникальный UUID для блока.

```python
block_id = Block.generate_id()  # "a1b2c3d4-..."
```

#### `px_to_norm(coords_px, page_width, page_height) -> tuple`

Конвертирует координаты из пикселей в нормализованные (0..1).

```python
coords_px = (100, 200, 500, 600)
coords_norm = Block.px_to_norm(coords_px, 1600, 2400)
# (0.0625, 0.0833, 0.3125, 0.25)
```

#### `norm_to_px(coords_norm, page_width, page_height) -> tuple`

Конвертирует нормализованные координаты в пиксели.

```python
coords_norm = (0.0625, 0.0833, 0.3125, 0.25)
coords_px = Block.norm_to_px(coords_norm, 1600, 2400)
# (100, 200, 500, 600)
```

### Методы экземпляра

#### `get_width_height_px() -> Tuple[int, int]`

Возвращает ширину и высоту блока в пикселях.

```python
width, height = block.get_width_height_px()
```

#### `get_width_height_norm() -> Tuple[float, float]`

Возвращает ширину и высоту в нормализованных координатах.

```python
width_norm, height_norm = block.get_width_height_norm()
```

#### `update_coords_px(new_coords_px, page_width, page_height)`

Обновляет координаты в пикселях и автоматически пересчитывает нормализованные.

```python
# При изменении zoom или размера страницы
new_coords = (200, 400, 1000, 1200)
block.update_coords_px(new_coords, 3200, 4800)
```

### Сериализация

```python
# В JSON
block_dict = block.to_dict()
json_str = json.dumps(block_dict, indent=2)

# Из JSON
restored_block = Block.from_dict(block_dict)
```

**Формат JSON:**

```json
{
  "id": "a1b2c3d4-...",
  "page_index": 0,
  "coords_px": [100, 200, 500, 600],
  "coords_norm": [0.0625, 0.0833, 0.3125, 0.25],
  "category": "Заголовок",
  "block_type": "text",
  "source": "user",
  "image_file": "crops/page_1_block_1.png",
  "ocr_text": "Распознанный текст"
}
```

---

## 📄 Класс `PageModel`

Модель страницы PDF с изображением и блоками.

### Атрибуты

| Поле | Тип | Описание |
|------|-----|----------|
| `page_index` | `int` | Индекс страницы (начиная с 0) |
| `image` | `PIL.Image.Image` | Отрендеренное изображение страницы |
| `blocks` | `List[Block]` | Список блоков разметки на странице |

### Properties

```python
page.width   # Ширина изображения в пикселях
page.height  # Высота изображения в пикселях
page.size    # (width, height)
```

### Создание

```python
from app.models import PageModel
from PIL import Image

# С реальным изображением
image = Image.open("page_0.png")
page = PageModel(page_index=0, image=image)

# Или с отрендеренным из PDF
from app.pdf_utils import open_pdf, render_page_to_image

doc = open_pdf("document.pdf")
image = render_page_to_image(doc, 0, zoom=2.0)
page = PageModel(page_index=0, image=image)
doc.close()
```

### Методы работы с блоками

#### `add_block(block: Block)`

Добавляет блок на страницу.

```python
page.add_block(block)
```

#### `remove_block(block_id: str) -> bool`

Удаляет блок по ID. Возвращает `True` если успешно.

```python
if page.remove_block("block-id-123"):
    print("Блок удалён")
```

#### `get_block_by_id(block_id: str) -> Optional[Block]`

Находит блок по ID.

```python
block = page.get_block_by_id("block-id-123")
if block:
    print(f"Найден: {block.category}")
```

#### `get_blocks_by_type(block_type: BlockType) -> List[Block]`

Возвращает все блоки заданного типа.

```python
text_blocks = page.get_blocks_by_type(BlockType.TEXT)
table_blocks = page.get_blocks_by_type(BlockType.TABLE)
```

#### `get_blocks_by_source(source: BlockSource) -> List[Block]`

Возвращает блоки из заданного источника.

```python
user_blocks = page.get_blocks_by_source(BlockSource.USER)
auto_blocks = page.get_blocks_by_source(BlockSource.AUTO)
```

### Сериализация

```python
# Без изображения (для JSON)
page_dict = page.to_dict(include_image=False)

# С изображением (base64, для полного сохранения)
page_dict = page.to_dict(include_image=True)
```

---

## 🔄 Helper функции

### Конвертация из legacy формата

```python
from app.models import create_block_from_legacy

# Legacy: x, y, width, height
block = create_block_from_legacy(
    x=100, y=200, width=400, height=200,
    page_index=0,
    page_width=1600,
    page_height=2400,
    block_type=BlockType.TEXT,
    is_auto=False,
    description="Описание блока"
)
```

### Конвертация в legacy формат

```python
from app.models import block_to_legacy_coords

x, y, width, height = block_to_legacy_coords(block)
```

### Конвертация форматов координат

```python
from app.models import coords_xywh_to_xyxy, coords_xyxy_to_xywh

# (x, y, w, h) → (x1, y1, x2, y2)
x1, y1, x2, y2 = coords_xywh_to_xyxy(100, 200, 400, 300)

# (x1, y1, x2, y2) → (x, y, w, h)
x, y, w, h = coords_xyxy_to_xywh(100, 200, 500, 500)
```

---

## 💡 Практические примеры

### Пример 1: Создание и работа со страницей

```python
from app.pdf_utils import open_pdf, render_page_to_image
from app.models import PageModel, Block, BlockType, BlockSource

# Рендерим страницу
doc = open_pdf("document.pdf")
image = render_page_to_image(doc, 0, zoom=2.0)

# Создаём модель страницы
page = PageModel(page_index=0, image=image)

# Добавляем блоки
block1 = Block.create(
    page_index=0,
    coords_px=(100, 100, 500, 300),
    page_width=page.width,
    page_height=page.height,
    category="Заголовок",
    block_type=BlockType.TEXT,
    source=BlockSource.USER
)

page.add_block(block1)

# Получаем все текстовые блоки
text_blocks = page.get_blocks_by_type(BlockType.TEXT)
print(f"Текстовых блоков: {len(text_blocks)}")

doc.close()
```

### Пример 2: Перенос разметки при изменении zoom

```python
# Исходная разметка при zoom=2.0
old_page_width = 1600
old_page_height = 2400

block = Block.create(
    page_index=0,
    coords_px=(100, 200, 500, 600),
    page_width=old_page_width,
    page_height=old_page_height,
    category="Блок",
    block_type=BlockType.TEXT,
    source=BlockSource.USER
)

# Нормализованные координаты сохранены
print(f"Norm координаты: {block.coords_norm}")

# Новая страница с zoom=3.0
new_page_width = 2400
new_page_height = 3600

# Пересчитываем в новые пиксели
new_coords_px = Block.norm_to_px(
    block.coords_norm,
    new_page_width,
    new_page_height
)

print(f"Новые px координаты: {new_coords_px}")
# Пропорции сохранены!
```

### Пример 3: Сохранение и загрузка разметки

```python
import json
from app.models import Block, BlockType, BlockSource

# Создаём блоки
blocks = [
    Block.create(0, (100, 100, 500, 300), 1600, 2400, "Заголовок", 
                BlockType.TEXT, BlockSource.USER),
    Block.create(0, (100, 400, 800, 900), 1600, 2400, "Таблица", 
                BlockType.TABLE, BlockSource.AUTO)
]

# Сохраняем в JSON
data = {
    "page_index": 0,
    "page_width": 1600,
    "page_height": 2400,
    "blocks": [b.to_dict() for b in blocks]
}

with open("markup.json", "w") as f:
    json.dump(data, f, indent=2)

# Загружаем
with open("markup.json", "r") as f:
    loaded_data = json.load(f)

restored_blocks = [Block.from_dict(b) for b in loaded_data["blocks"]]
print(f"Загружено блоков: {len(restored_blocks)}")
```

---

## 🔗 Обратная совместимость

Старые классы `Page` и `Document` сохранены для совместимости с существующим GUI кодом:

```python
from app.models import Page, Document

# Legacy формат (используется в GUI)
page = Page(page_number=0, width=1600, height=2400)
document = Document(pdf_path="file.pdf", pages=[page])
```

---

## 📝 Рекомендации

1. **Всегда используйте `Block.create()`** для создания новых блоков — автоматически вычисляет norm координаты
2. **Храните нормализованные координаты** в JSON для переносимости между версиями PDF
3. **Используйте `PageModel`** вместо `Page` для новых функций — интеграция с изображением
4. **ID блоков** позволяют отслеживать изменения и связи между блоками
5. **Category** используйте для группировки блоков ("Технические характеристики", "Схема")

---

## 🧪 Тестирование

Запустите примеры:

```bash
python examples/test_models.py
```

Примеры покрывают:
- Создание блоков
- Конвертацию координат
- Работу с PageModel
- Сериализацию/десериализацию
- Legacy конвертацию
- Обновление координат

---

## 🔍 См. также

- [`docs/pdf_rendering.md`](pdf_rendering.md) — рендеринг PDF в изображения
- [`examples/test_models.py`](../examples/test_models.py) — примеры кода
- [`app/models.py`](../app/models.py) — исходный код

