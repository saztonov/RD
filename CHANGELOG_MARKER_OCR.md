# Changelog: Marker + OCR интеграция

## Версия 1.2.0 - Редактируемые промпты OCR

### Новая функциональность

#### Система управления промптами

**Новая папка:** `prompts/`

Все промпты для OCR теперь хранятся в отдельных файлах:
- `ocr_text.txt` - для TEXT блоков
- `ocr_table.txt` - для TABLE блоков
- `ocr_image_description.txt` - для IMAGE блоков
- `ocr_full_page.txt` - для полной страницы
- `README.md` - документация по промптам

**Преимущества:**
- ✅ Редактирование без изменения кода
- ✅ Быстрая настройка под разные типы документов
- ✅ Версионирование промптов
- ✅ Лёгкий откат к предыдущим версиям

#### Функция загрузки промптов

**Новая функция в `app/ocr.py`:**

```python
def load_prompt(prompt_file: str) -> str
```

Автоматически загружает промпт из файла при каждом запуске OCR.

### Изменённые файлы

#### `app/ocr.py`

**Добавлено:**
```python
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

def load_prompt(prompt_file: str) -> str:
    """Загрузить промпт из файла"""
```

**Модифицировано:**
- `LocalVLMBackend.recognize()` - использует `ocr_full_page.txt`
- `run_ocr_for_blocks()` - загружает промпты по типу блока

#### `app/gui/main_window.py`

**Модифицировано:**
- `_run_local_vlm_ocr_blocks()` - использует промпты из файлов
- `_run_chandra_ocr_blocks()` - использует промпты из файлов

#### `examples/test_marker_ocr_workflow.py`

**Модифицировано:**
- Использует `load_prompt()` для каждого типа блока

### Новые файлы

#### Промпты
- `prompts/ocr_text.txt` - промпт для текста
- `prompts/ocr_table.txt` - промпт для таблиц
- `prompts/ocr_image_description.txt` - промпт для изображений
- `prompts/ocr_full_page.txt` - промпт для полной страницы
- `prompts/README.md` - документация по промптам

#### Документация
- `docs/PROMPTS_CUSTOMIZATION.md` - руководство по настройке промптов

### Использование

#### Редактирование промпта

1. Откройте файл в текстовом редакторе:
   ```bash
   notepad prompts\ocr_image_description.txt
   ```

2. Измените промпт:
   ```
   Опиши изображение кратко.
   ```

3. Сохраните файл (UTF-8)

4. Запустите OCR снова

#### Примеры кастомизации

**Технические чертежи:**
```
Опиши технический чертёж.
Укажи размеры, масштаб, обозначения.
Перечисли все элементы и спецификацию.
```

**Фотографии:**
```
Опиши что изображено на фотографии.
Укажи объекты, цвета, композицию.
```

### Обновления в README.md

- ✅ Добавлена секция "Настройка промптов"
- ✅ Ссылка на `prompts/README.md`
- ✅ Ссылка на `docs/PROMPTS_CUSTOMIZATION.md`

### Совместимость

Полностью обратно совместимо с версией 1.1.0:
- Если файл промпта не найден - используется fallback
- Старый код продолжает работать

### API изменения

**Новая функция:**
```python
from app.ocr import load_prompt

# Загрузить промпт
prompt = load_prompt("ocr_text.txt")
```

**Обновлённая сигнатура:**
```python
def recognize(self, image: Image.Image, prompt: Optional[str] = None) -> str
```
Если `prompt=None`, автоматически загружается из файла.

---

## Версия 1.1.0 - Обработка блоков по типам

### Новая функциональность

#### 1. OCR с учетом типов блоков

После Marker разметки, при запуске OCR каждый блок обрабатывается согласно его типу:

- **TEXT** → распознавание текста (Chandra/Qwen)
- **TABLE** → распознавание таблиц (Chandra/Qwen)
- **IMAGE** → детальное описание на русском языке (Qwen VLM)

#### 2. Описание изображений

Для IMAGE блоков используется специальный промпт:
- Распознавание всех видимых элементов
- Извлечение текста на русском языке
- Технические параметры и размеры
- Описание структуры, компонентов, связей

#### 3. Структурированный Markdown

Новая функция генерации markdown документа:
- Соблюдение структуры разметки
- Вставка описаний изображений
- Ссылки на кропы изображений
- Сортировка блоков по вертикальной позиции

### Изменённые файлы

#### `app/ocr.py`

**Новые функции:**

```python
def run_ocr_for_blocks(
    blocks: List[Block], 
    ocr_backend: OCRBackend, 
    base_dir: str = "", 
    image_description_backend: Optional[OCRBackend] = None
) -> None
```
- Обработка блоков с учетом типа
- Отдельный движок для описания изображений
- Специальный промпт для IMAGE блоков

```python
def generate_structured_markdown(
    pages: List, 
    output_path: str, 
    images_dir: str = "images"
) -> str
```
- Генерация markdown из размеченных блоков
- Вставка описаний и ссылок на изображения
- Группировка по страницам

#### `app/gui/main_window.py`

**Модифицированные функции:**

```python
def _run_local_vlm_ocr_blocks(api_base: str, model_name: str)
```
- Обработка IMAGE блоков с описанием
- Сохранение кропов в `temp_crops/`
- Вызов `_generate_structured_markdown()`

```python
def _run_chandra_ocr_blocks(method: str = "hf")
```
- TEXT/TABLE через Chandra OCR
- IMAGE через VLM сервер
- Комбинированный подход для оптимального качества

**Новая функция:**

```python
def _generate_structured_markdown()
```
- Диалог выбора пути сохранения
- Вызов `generate_structured_markdown()`
- Уведомление о результате

### Новые файлы

#### Документация

- `docs/MARKER_OCR_INTEGRATION.md` - полная документация интеграции
- `docs/QUICK_START_MARKER_OCR.md` - быстрый старт
- `CHANGELOG_MARKER_OCR.md` - этот файл

#### Примеры

- `examples/test_marker_ocr_workflow.py` - пример полного workflow

### Изменения в README.md

- ✅ Добавлена секция "Недавние обновления"
- ✅ Обновлена секция OCR с информацией о типах
- ✅ Реорганизована секция документации
- ✅ Добавлены ссылки на новые документы

### Workflow использования

```
1. Открыть PDF
   ↓
2. Marker разметка (Ctrl+M)
   ↓
3. Запустить OCR (Ctrl+R)
   → Режим: По блокам
   → Движок: LocalVLM / Chandra
   ↓
4. Генерация структурированного Markdown
   ↓
5. Результат:
   - recognized_document.md
   - temp_crops/
     - page0_block*.png
```

### Требования

**Обязательно:**
- Python 3.11+
- PySide6
- Marker (для разметки)

**Для OCR:**
- Локальный VLM сервер (Qwen3-VL) на `http://127.0.0.1:1234/v1`
- ИЛИ Chandra OCR (`pip install chandra-ocr`)

### Примеры использования

#### Через GUI

```
1. Файл → Открыть PDF
2. Инструменты → Marker разметка (Ctrl+M)
3. Инструменты → Запустить OCR (Ctrl+R)
   - Выбрать "По блокам"
   - Выбрать "Локальный VLM сервер"
4. Да → Сгенерировать структурированный Markdown
```

#### Через код

```python
from app.marker_integration import segment_with_marker
from app.ocr import create_ocr_engine, generate_structured_markdown

# 1. Marker разметка
pages = segment_with_marker(pdf_path, pages, page_images)

# 2. OCR по блокам
vlm_engine = create_ocr_engine("local_vlm")
for page in pages:
    for block in page.blocks:
        if block.block_type == BlockType.IMAGE:
            block.ocr_text = vlm_engine.recognize(crop, prompt=image_prompt)
        else:
            block.ocr_text = vlm_engine.recognize(crop)

# 3. Генерация markdown
generate_structured_markdown(pages, "output.md")
```

### Известные ограничения

1. **VLM сервер** должен быть запущен для IMAGE описаний
2. **Время обработки** IMAGE блоков дольше чем TEXT/TABLE
3. **Кропы изображений** сохраняются в `temp_crops/` (нужна очистка)
4. **Язык описаний** - только русский (можно модифицировать промпт)

### Roadmap

- [ ] Настройка языка описаний изображений
- [ ] Автоматическая очистка temp_crops
- [ ] Прогресс-бар с детализацией по типам
- [ ] Опциональное встраивание кропов в markdown (base64)
- [ ] Экспорт в DOCX со встроенными изображениями

### Ссылки

- Chandra OCR: https://github.com/datalab-to/chandra
- Документация: [docs/MARKER_OCR_INTEGRATION.md](docs/MARKER_OCR_INTEGRATION.md)
- Быстрый старт: [docs/QUICK_START_MARKER_OCR.md](docs/QUICK_START_MARKER_OCR.md)

---

**Автор:** AI Assistant  
**Дата:** 2025-11-30  
**Версия:** 1.1.0

