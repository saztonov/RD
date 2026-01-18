# rd_pipeline

**Layer 1** — Бизнес-логика OCR и PDF обработки.

Содержит OCR backends, PDF утилиты, препроцессинг изображений и генераторы вывода.

## Зависимости

- `rd_domain` — доменные модели
- PyMuPDF (fitz) — работа с PDF
- Pillow — обработка изображений
- httpx — HTTP клиент для OCR API

## Модули

### ocr/
OCR движки и протоколы.

#### Протокол OCRBackend

```python
from rd_pipeline.ocr import OCRBackend

class OCRBackend(Protocol):
    def recognize(
        self,
        image: Image.Image,
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        timeout_multiplier: int = 1
    ) -> str: ...

    def supports_native_pdf() -> bool: ...
```

#### Фабрика

```python
from rd_pipeline.ocr import create_ocr_engine

# Создание OCR движка
engine = create_ocr_engine(backend="openrouter")  # или "datalab", "dummy"

# Распознавание
result = engine.recognize(image, prompt={"system": "...", "user": "..."})
```

#### Backends

| Backend | Описание |
|---------|----------|
| `openrouter` | OpenRouter API (Claude, GPT-4V и др.) |
| `datalab` | DataLab OCR API |
| `dummy` | Тестовый backend (возвращает заглушки) |

### pdf/
Утилиты для работы с PDF.

```python
from rd_pipeline.pdf import PDFDocument

# Контекстный менеджер для безопасной работы с PDF
with PDFDocument(pdf_path) as doc:
    page_count = doc.page_count
    image = doc.render_page(0, dpi=300)
    text = doc.extract_text(0)
```

**Константы:**
- `PDF_RENDER_DPI = 300` — DPI для OCR
- `PDF_PREVIEW_DPI = 150` — DPI для превью

### processing/
Препроцессинг изображений.

```python
from rd_pipeline.processing import preprocess_image, PreprocessConfig

# Конфигурация препроцессинга
config = PreprocessConfig(
    grayscale=True,
    contrast=1.5,
    sharpen=True,
    denoise=False
)

# Препроцессинг
processed = preprocess_image(image, config)
```

**Режимы по типам блоков:**

| Тип | Grayscale | Contrast | Sharpen | Denoise |
|-----|-----------|----------|---------|---------|
| TEXT | Да | 1.5 | Да | Нет |
| IMAGE | Нет | Нет | Нет | Нет |
| STAMP | Да | Нет | Нет | MedianFilter(3) |

#### Two-pass обработка

```python
from rd_pipeline.processing import TwoPassProcessor

processor = TwoPassProcessor(ocr_engine)
results = processor.process(pdf_path, blocks)
```

### output/
Генераторы Markdown вывода.

```python
from rd_pipeline.output import generate_markdown

# Генерация Markdown из результатов OCR
markdown = generate_markdown(blocks, include_images=True)
```

### common/
Общие утилиты.

| Модуль | Описание |
|--------|----------|
| `block_utils` | Утилиты для работы с блоками (`get_block_armor_id`, `collect_block_groups`) |
| `linked_blocks` | Связывание IMAGE+TEXT блоков (`build_linked_blocks_index`) |
| `sanitizers` | Очистка и нормализация текста (`sanitize_html`, `sanitize_markdown`) |
| `image_data` | Работа с изображениями (`extract_image_ocr_data`, `is_image_ocr_json`) |
| `stamp_utils` | Обработка штампов (`parse_stamp_json`, `find_page_stamp`, `propagate_stamp_data`) |
| `html_template` | HTML шаблоны (`HTML_TEMPLATE`, `HTML_FOOTER`, `get_html_header`) |

```python
from rd_pipeline import (
    # Санитайзеры
    sanitize_html, sanitize_markdown,
    # Штампы
    parse_stamp_json, find_page_stamp, propagate_stamp_data,
    # Связанные блоки
    build_linked_blocks_index,
    # Утилиты блоков
    get_block_armor_id, collect_block_groups,
)
```

### utils/
Вспомогательные утилиты.

```python
from rd_pipeline.utils import get_memory_usage

memory_mb = get_memory_usage()
```

## Правила импорта

rd_pipeline — средний слой:
- Зависит от `rd_domain`
- НЕ импортирует из `rd_adapters`, `apps/`
- Может импортироваться `rd_adapters` и `apps/`

```
rd_domain (Layer 0)
    ↑
rd_pipeline (Layer 1)  ← вы здесь
    ↑
rd_adapters (Layer 2)
    ↑
apps/ (Application Layer)
```
