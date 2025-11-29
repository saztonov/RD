# ⚡ Модели данных — Краткое резюме

## Что реализовано

### ✅ Новые Enums

```python
class BlockSource(Enum):
    USER = "user"  # Ручное создание
    AUTO = "auto"  # Автосегментация
```

### ✅ Обновлённый класс Block

**Ключевые поля:**
- `id: str` — UUID
- `coords_px: (x1, y1, x2, y2)` — пиксели
- `coords_norm: (x1, y1, x2, y2)` — 0..1
- `category: str` — описание
- `block_type: BlockType` — TEXT/TABLE/IMAGE
- `source: BlockSource` — USER/AUTO
- `image_file: Optional[str]`
- `ocr_text: Optional[str]`

**Создание:**

```python
block = Block.create(
    page_index=0,
    coords_px=(100, 200, 500, 600),
    page_width=1600,
    page_height=2400,
    category="Заголовок",
    block_type=BlockType.TEXT,
    source=BlockSource.USER
)
```

**Автоматически:**
- Генерирует UUID
- Вычисляет coords_norm

### ✅ Новый класс PageModel

```python
page = PageModel(page_index=0, image=pil_image)
page.add_block(block)

# Фильтрация
text_blocks = page.get_blocks_by_type(BlockType.TEXT)
user_blocks = page.get_blocks_by_source(BlockSource.USER)

# Поиск
block = page.get_block_by_id("block-uuid")
```

**Properties:**
- `width`, `height`, `size` — из изображения

### ✅ Конвертация координат

```python
# px → norm
coords_norm = Block.px_to_norm(coords_px, page_width, page_height)

# norm → px
coords_px = Block.norm_to_px(coords_norm, page_width, page_height)

# Обновить блок
block.update_coords_px(new_coords, page_width, page_height)
```

### ✅ Helper функции

```python
# Legacy формат (x, y, w, h)
block = create_block_from_legacy(x, y, width, height, ...)

# Обратно в legacy
x, y, w, h = block_to_legacy_coords(block)

# Форматы координат
x1, y1, x2, y2 = coords_xywh_to_xyxy(x, y, w, h)
x, y, w, h = coords_xyxy_to_xywh(x1, y1, x2, y2)
```

### ✅ Сериализация

```python
# В JSON
data = block.to_dict()
json.dump(data, f)

# Из JSON
block = Block.from_dict(data)

# PageModel
page_data = page.to_dict(include_image=False)  # Без изображения
```

---

## 🎯 Зачем две системы координат?

### coords_px — абсолютные

- Точные координаты на отрендеренном изображении
- Зависят от zoom при рендеринге
- Используются для обрезки блоков

### coords_norm — относительные (0..1)

- Не зависят от zoom
- Переносятся между версиями PDF
- Позволяют адаптировать разметку к новым размерам

### Пример

```python
# Исходная разметка zoom=2.0
block = Block.create(..., coords_px=(100, 200, 500, 600))
# coords_norm = (0.0625, 0.0833, 0.3125, 0.25)

# Новая страница zoom=3.0 (размер 2400x3600)
new_coords = Block.norm_to_px(block.coords_norm, 2400, 3600)
# (150, 300, 750, 900) — пропорции сохранены!
```

---

## 📖 Документация

- **Полная:** `docs/DATA_MODELS.md`
- **Примеры:** `examples/test_models.py`
- **Код:** `app/models.py`

## 🚀 Запуск примеров

```bash
python examples/test_models.py
```

7 примеров:
1. Создание блоков
2. Конвертация координат
3. Legacy конвертация
4. PageModel
5. Сериализация
6. Обновление при изменении zoom
7. Helper функции

---

## ✨ Ключевые преимущества

1. **UUID блоков** — отслеживание изменений
2. **Нормализованные координаты** — перенос разметки
3. **Автоматическая конвертация** — px ↔ norm
4. **Интеграция с PIL** — PageModel с изображением
5. **Категоризация** — category + type + source
6. **Обратная совместимость** — legacy классы сохранены

---

## 🔄 Миграция старого кода

```python
# Старый код (legacy)
block_old = Block(x=100, y=200, width=400, height=200, ...)

# Новый код
block_new = create_block_from_legacy(
    x=100, y=200, width=400, height=200,
    page_index=0,
    page_width=page_width,
    page_height=page_height,
    ...
)
```

**Или используйте helper:**

```python
x1, y1, x2, y2 = coords_xywh_to_xyxy(x, y, width, height)
coords_px = (x1, y1, x2, y2)
```

