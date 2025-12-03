# Миграция на ngrok API

## Выполненные изменения

### 1. Удалены локальные компоненты

**Удаленные файлы:**
- `app/marker_integration.py` - локальная интеграция с Marker
- `docs/MARKER_OCR_INTEGRATION.md`
- `docs/QUICK_START_MARKER_OCR.md`
- `docs/LOCAL_VLM_OCR.md`
- `docs/CHANDRA_OCR.md`

**Удалены из requirements.txt:**
- `marker-pdf`
- `requests` (заменен на httpx)

**Добавлено в requirements.txt:**
- `httpx>=0.27.0`

### 2. Новые файлы

**app/config.py**
```python
NGROK_BASE_URL = "https://louvred-madie-gigglier.ngrok-free.dev"

def get_marker_base_url() -> str:
    return f"{NGROK_BASE_URL}/api/v1/segment"

def get_lm_base_url() -> str:
    return f"{NGROK_BASE_URL}/api/v1/lm/chat"
```

**app/segmentation_api.py**
- `segment_with_api()` - замена `segment_with_marker()`
- `segment_pdf_sync()` - синхронная отправка PDF на API
- `segment_pdf_async()` - асинхронная версия

**docs/API_INTEGRATION.md**
- Документация по работе с ngrok API

### 3. Обновленные файлы

**app/ocr_engines.py**
- `LocalVLMEngine` теперь использует `get_lm_base_url()` из config
- Удален параметр `api_base` (игнорируется)
- Используется `httpx` вместо `openai` библиотеки

**app/ocr.py**
- `LocalVLMBackend` переписан на `httpx`
- Использует `get_lm_base_url()` вместо `http://127.0.0.1:1234/v1`

**app/gui/task_manager.py**
- `MarkerWorker` переименован в комментариях на "API сегментация"
- Импорт изменен: `from app.segmentation_api import segment_with_api`

**app/gui/main_window.py**
- Обновлены сообщения: "Marker" → "Сегментация"
- Функции `_marker_segment_pdf()` и `_marker_segment_all_pages()` работают через API

**app/gui/ocr_dialog.py**
- `vlm_server_url` установлен в пустую строку (не используется)

**app/gui/ocr_manager.py**
- `run_chandra_ocr_blocks_with_output()` обновлен: удален параметр `api_base`

## Архитектура

### Сегментация PDF

```
PDF файл → app/segmentation_api.py → POST /api/v1/segment
                                      ↓
                                   ngrok endpoint
                                      ↓
                                   FastAPI + Marker (Docker)
                                      ↓
                                   JSON структура
                                      ↓
                                   app/models.Block
```

### OCR через LLM

```
PIL.Image → app/ocr_engines.LocalVLMEngine → POST /api/v1/lm/chat
                                               ↓
                                            ngrok endpoint
                                               ↓
                                            FastAPI proxy
                                               ↓
                                            LM Studio
                                               ↓
                                            Распознанный текст
```

## Таймауты

Все HTTP запросы используют таймаут **600 секунд (10 минут)** для обработки больших документов.

## Зависимости

### Удалены
- `marker-pdf` - больше не требуется локальная установка
- `requests` - заменен на httpx

### Добавлены
- `httpx>=0.27.0` - современный HTTP клиент с async/sync поддержкой

### Сохранены
- `openai` - используется только для OpenRouter (опционально)
- `chandra-ocr` - опциональная зависимость (закомментирована)

## Конфигурация

Для изменения ngrok endpoint отредактируйте `app/config.py`:

```python
NGROK_BASE_URL = "https://your-new-endpoint.ngrok-free.dev"
```

## Тестирование

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Запустите приложение:
```bash
python -m app.main
```

3. Проверьте функции:
   - Marker разметка (Ctrl+M)
   - Marker все страницы (Ctrl+Shift+M)
   - OCR блоков (локальный VLM)
   - OCR через OpenRouter

## Обратная совместимость

- Старые JSON файлы с разметкой остаются совместимыми
- Промпты из `prompts/` продолжают работать
- R2 Storage интеграция не изменена
- OpenRouter остался без изменений

## Производительность

- Сегментация: зависит от скорости ngrok endpoint
- OCR: зависит от скорости LM Studio через ngrok
- Таймаут: 600 секунд на запрос

## Известные ограничения

1. Требуется стабильное интернет-соединение
2. Ngrok endpoint должен быть доступен
3. Размер PDF ограничен возможностями ngrok/FastAPI
4. Локальные модели больше не поддерживаются

