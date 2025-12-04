# API Integration через ngrok

Приложение использует единый публичный endpoint через ngrok для сегментации PDF и LLM-обработки.

## Endpoint

```
https://louvred-madie-gigglier.ngrok-free.dev
```

## API Endpoints

### 1. POST /api/v1/segment

Сегментация PDF документа через Marker.

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body: файл PDF в поле `file`

**Response:**
```json
{
  "pages": [
    {
      "width": 595.0,
      "height": 842.0,
      "blocks": [
        {
          "bbox": [x1, y1, x2, y2],
          "type": "Text|Table|Image"
        }
      ]
    }
  ]
}
```

### 2. POST /api/v1/lm/chat

Проксирует запросы в LM Studio (OpenAI-совместимый API).

**Request:**
- Method: `POST`
- Content-Type: `application/json`
- Body:
```json
{
  "model": "qwen3-vl-32b-instruct",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "Промпт"},
        {
          "type": "image_url",
          "image_url": {"url": "data:image/png;base64,..."}
        }
      ]
    }
  ],
  "max_tokens": 16384,
  "temperature": 0.1
}
```

**Response:**
```json
{
  "choices": [
    {
      "message": {
        "content": "Распознанный текст..."
      }
    }
  ]
}
```

## Конфигурация

Endpoint настраивается в `app/config.py`:

```python
NGROK_BASE_URL = "https://louvred-madie-gigglier.ngrok-free.dev"

def get_marker_base_url() -> str:
    return f"{NGROK_BASE_URL}/api/v1/segment"

def get_lm_base_url() -> str:
    return f"{NGROK_BASE_URL}/api/v1/lm/chat"
```

## Использование

### Сегментация PDF

```python
from app.segmentation_api import segment_with_api

# Разметка всего документа
updated_pages = segment_with_api(
    pdf_path="document.pdf",
    pages=pages,
    page_images=None,
    page_range=None,
    category="my_category"
)

# Разметка одной страницы
updated_pages = segment_with_api(
    pdf_path="document.pdf",
    pages=pages,
    page_images=None,
    page_range=[0],  # первая страница
    category=""
)
```

### OCR через LLM

```python
from app.ocr_engines import create_ocr_engine

# Создание engine (автоматически использует ngrok)
engine = create_ocr_engine("local_vlm", model_name="qwen3-vl-32b-instruct")

# Распознавание
text = engine.recognize(image, prompt="Распознай текст")
```

## Таймауты

Все запросы используют таймаут 600 секунд (10 минут) для обработки больших документов.

## Зависимости

- `httpx>=0.27.0` - HTTP клиент с поддержкой async/sync



