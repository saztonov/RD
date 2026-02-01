# DeepSeek-OCR-2 API - Инструкция для Claude Code

## Описание сервиса

OCR API на базе модели DeepSeek-OCR-2 для распознавания текста и таблиц из изображений и PDF документов. Сервис развёрнут локально в Docker с GPU ускорением и доступен через ngrok туннель.

## Доступ к API

- **Публичный URL:** `https://louvred-madie-gigglier.ngrok-free.dev`
- **Локальный URL:** `http://localhost:8001`

## Endpoints

### GET /health
Проверка состояния сервиса.

```bash
curl https://louvred-madie-gigglier.ngrok-free.dev/health
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
curl -X POST https://louvred-madie-gigglier.ngrok-free.dev/ocr \
  -F "file=@screenshot.png" \
  -F "mode=markdown"
```

### Распознать первую страницу PDF
```bash
curl -X POST https://louvred-madie-gigglier.ngrok-free.dev/ocr \
  -F "file=@document.pdf" \
  -F "mode=markdown" \
  -F "page=1"
```

### Распознать диапазон страниц PDF (2-5)
```bash
curl -X POST https://louvred-madie-gigglier.ngrok-free.dev/ocr \
  -F "file=@document.pdf" \
  -F "mode=markdown" \
  -F "first_page=2" \
  -F "last_page=5"
```

### Распознать весь PDF (все страницы)
```bash
curl -X POST https://louvred-madie-gigglier.ngrok-free.dev/ocr \
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
(Invoke-WebRequest -Uri "https://louvred-madie-gigglier.ngrok-free.dev/health" -UseBasicParsing).Content
```

### OCR изображения
```powershell
$response = Invoke-RestMethod -Uri "https://louvred-madie-gigglier.ngrok-free.dev/ocr" -Method Post -Form @{
    file = Get-Item "image.png"
    mode = "markdown"
}
$response.markdown | Out-File "result.md" -Encoding UTF8
```

## Примеры для Python

```python
import requests

# Проверка здоровья
response = requests.get("https://louvred-madie-gigglier.ngrok-free.dev/health")
print(response.json())

# OCR изображения
with open("image.png", "rb") as f:
    response = requests.post(
        "https://louvred-madie-gigglier.ngrok-free.dev/ocr",
        files={"file": f},
        data={"mode": "markdown"}
    )
result = response.json()
print(result["markdown"])

# OCR первой страницы PDF
with open("document.pdf", "rb") as f:
    response = requests.post(
        "https://louvred-madie-gigglier.ngrok-free.dev/ocr",
        files={"file": f},
        data={"mode": "markdown", "page": "1"}
    )
result = response.json()
print(result["markdown"])
```

## Рекомендации

1. **Для больших PDF** — используйте параметр `page` или `first_page`/`last_page` для обработки по частям
2. **Таймауты** — обработка одной страницы занимает ~15-20 секунд, устанавливайте соответствующие таймауты
3. **Размер файла** — рекомендуемый максимальный размер запроса 50 MB
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

### Запуск ngrok туннеля
```bash
C:\ngrok\ngrok.exe http 8001
```

## Примечания по ngrok

- Используется домен: `louvred-madie-gigglier.ngrok-free.dev`
- При первом обращении через ngrok бесплатный аккаунт показывает интерстициальную страницу
- Для API запросов добавляйте заголовок `ngrok-skip-browser-warning: true`
