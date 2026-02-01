# DeepSeek-OCR-2 API - Инструкция для Claude Code

## Описание сервиса

OCR API на базе модели DeepSeek-OCR-2 для распознавания текста и таблиц из изображений и PDF документов. Сервис развёрнут локально в Docker с GPU ускорением и доступен через публичный URL.

## Доступ к API

- **Публичный URL:** `https://youtu.pnode.site`
- **Локальный URL:** `http://localhost:8001`

## Endpoints

### GET /health
Проверка состояния сервиса.

```bash
curl https://youtu.pnode.site/health
```

**Ответ:**
```json
{"status": "ok", "model_loaded": true}
```

### POST /ocr
Распознавание текста из изображения или PDF.

**Параметры (multipart/form-data):**

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| `file` | file | Да | Изображение или PDF файл |
| `mode` | string | Нет | Режим: `markdown` (по умолчанию) или `text` |
| `page` | int | Нет | Номер страницы PDF (1-based) |
| `first_page` | int | Нет | Первая страница диапазона |
| `last_page` | int | Нет | Последняя страница диапазона |

**Поддерживаемые форматы:**
- Изображения: PNG, JPEG, WebP, BMP, TIFF
- Документы: PDF

## Примеры использования

### Распознать изображение
```bash
curl -X POST https://youtu.pnode.site/ocr \
  -F "file=@screenshot.png" \
  -F "mode=markdown"
```

### Распознать первую страницу PDF
```bash
curl -X POST https://youtu.pnode.site/ocr \
  -F "file=@document.pdf" \
  -F "mode=markdown" \
  -F "page=1"
```

### Распознать диапазон страниц PDF (2-5)
```bash
curl -X POST https://youtu.pnode.site/ocr \
  -F "file=@document.pdf" \
  -F "mode=markdown" \
  -F "first_page=2" \
  -F "last_page=5"
```

### Распознать весь PDF (все страницы)
```bash
curl -X POST https://youtu.pnode.site/ocr \
  -F "file=@document.pdf" \
  -F "mode=markdown"
```

## Формат ответа

```json
{
  "markdown": "# Заголовок\n\nТекст документа...",
  "pages": 1,
  "success": true,
  "error": null
}
```

| Поле | Тип | Описание |
|------|-----|----------|
| `markdown` | string | Распознанный текст в формате Markdown |
| `pages` | int | Количество обработанных страниц |
| `success` | bool | Успешность операции |
| `error` | string/null | Сообщение об ошибке (если есть) |

## Примеры для PowerShell

### Проверка здоровья
```powershell
(Invoke-WebRequest -Uri "https://youtu.pnode.site/health" -UseBasicParsing).Content
```

### OCR изображения
```powershell
$response = Invoke-RestMethod -Uri "https://youtu.pnode.site/ocr" -Method Post -Form @{
    file = Get-Item "image.png"
    mode = "markdown"
}
$response.markdown | Out-File "result.md" -Encoding UTF8
```

## Примеры для Python

```python
import requests

# Проверка здоровья
response = requests.get("https://youtu.pnode.site/health")
print(response.json())

# OCR изображения
with open("image.png", "rb") as f:
    response = requests.post(
        "https://youtu.pnode.site/ocr",
        files={"file": f},
        data={"mode": "markdown"}
    )
result = response.json()
print(result["markdown"])

# OCR первой страницы PDF
with open("document.pdf", "rb") as f:
    response = requests.post(
        "https://youtu.pnode.site/ocr",
        files={"file": f},
        data={"mode": "markdown", "page": "1"}
    )
result = response.json()
print(result["markdown"])
```

## Рекомендации

1. **Для больших PDF** — используйте параметр `page` или `first_page`/`last_page` для обработки по частям
2. **Таймауты** — обработка одной страницы занимает ~15-20 секунд, устанавливайте соответствующие таймауты
3. **Размер файла** — максимальный размер запроса 30 MB (ограничение pnode)
4. **Качество** — для лучшего распознавания используйте изображения с разрешением не менее 200 DPI

## Управление сервисом

### Запуск Docker контейнера
```bash
cd c:\Users\svarovsky\PycharmProjects\DSK2
docker-compose up -d
```

### Остановка
```bash
docker-compose down
```

### Просмотр логов
```bash
docker-compose logs -f ocr-api
```

### Запуск pnode туннеля
```bash
start-pnode --token yJCjre7S7XOPibogOCtkPCPtfyKGTSBubiMVyJroX3ht0rZJAXPK2jimB6Xe --port 8001
```

## Лимиты (бесплатный план pnode)

- 10 000 запросов в день
- 10 GB трафика в день
- Максимальный размер запроса: 30 MB
- Скорость сети: 15 Мбит/с
