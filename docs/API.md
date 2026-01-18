# REST API спецификация

Remote OCR Server API для обработки PDF документов.

## Общие сведения

- **Base URL:** `http://localhost:18000`
- **Аутентификация:** Header `X-API-Key` (опционально, если настроен `API_KEY` в `.env`)
- **Формат данных:** JSON

## Служебные endpoints

### GET /health

Health check сервера.

**Ответ:**
```json
{"ok": true}
```

### GET /queue

Статус очереди задач.

**Ответ:**
```json
{
  "can_accept": true,
  "size": 5,
  "max": 100
}
```

---

## Jobs API (`/jobs`)

Управление OCR задачами.

### POST /jobs/init

Инициализация задачи с получением presigned URLs для прямой загрузки файлов в R2.

**Параметры (Form):**

| Параметр | Тип | Обязателен | Описание |
|----------|-----|------------|----------|
| client_id | string | Да | ID клиента |
| document_id | string | Да | ID документа |
| document_name | string | Да | Имя документа |
| node_id | string | Да | ID узла в дереве проектов |
| pdf_size | int | Да | Размер PDF в байтах |
| blocks_size | int | Да | Размер blocks.json в байтах |
| task_name | string | Нет | Название задачи |
| engine | string | Нет | OCR движок (`openrouter`, `datalab`). По умолчанию: `openrouter` |
| text_model | string | Нет | Модель для TEXT блоков |
| table_model | string | Нет | Модель для TABLE блоков |
| image_model | string | Нет | Модель для IMAGE блоков |
| stamp_model | string | Нет | Модель для STAMP блоков |

**Ответ:**
```json
{
  "job_id": "uuid",
  "presigned_urls": {
    "pdf": "https://...",
    "blocks": "https://..."
  },
  "r2_prefix": "n/{node_id}",
  "pdf_key": "n/{node_id}/{document_name}.pdf",
  "blocks_key": "n/{node_id}/blocks.json"
}
```

**Ошибки:**
- `400` — PDF или blocks слишком большие (макс. 500MB и 50MB)
- `503` — Очередь переполнена

### POST /jobs/{job_id}/confirm

Подтверждение загрузки файлов и запуск обработки.

**Параметры (Form):**

| Параметр | Тип | Описание |
|----------|-----|----------|
| start_immediately | bool | Запустить сразу (по умолчанию: true) |

**Ответ:**
```json
{
  "id": "uuid",
  "status": "queued",
  "progress": 0
}
```

### POST /jobs (Legacy v1)

Создание задачи с загрузкой файлов через multipart/form-data.

**Параметры (Form + Files):**

| Параметр | Тип | Описание |
|----------|-----|----------|
| pdf | File | PDF документ |
| blocks_file | File | JSON с блоками |
| client_id | string | ID клиента |
| document_id | string | ID документа |
| document_name | string | Имя документа |
| ... | | (остальные как в /init) |

### GET /jobs

Список задач.

**Query параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| document_id | string | Фильтр по документу (опционально) |

**Ответ:**
```json
[
  {
    "id": "uuid",
    "status": "done",
    "progress": 100,
    "document_name": "document.pdf",
    "task_name": "OCR Task",
    "document_id": "uuid",
    "node_id": "uuid",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:10:00Z",
    "error_message": null
  }
]
```

### GET /jobs/changes

Инкрементальные обновления задач.

**Query параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| since | string | ISO timestamp для фильтрации |

**Ответ:**
```json
{
  "jobs": [...],
  "server_time": "2024-01-01T00:00:00Z"
}
```

### GET /jobs/{job_id}

Информация о задаче.

**Ответ:**
```json
{
  "id": "uuid",
  "status": "processing",
  "progress": 50,
  "document_name": "document.pdf",
  "task_name": "OCR Task",
  "document_id": "uuid",
  "node_id": "uuid",
  "r2_prefix": "n/{node_id}",
  "created_at": "...",
  "updated_at": "...",
  "error_message": null
}
```

**Статусы задач:**
- `pending_upload` — Ожидание загрузки файлов
- `draft` — Черновик
- `queued` — В очереди
- `processing` — Обработка
- `done` — Завершена
- `error` — Ошибка
- `cancelled` — Отменена

### GET /jobs/{job_id}/details

Детальная информация с настройками и статистикой.

**Ответ:**
```json
{
  "id": "uuid",
  "status": "done",
  "job_settings": {
    "text_model": "anthropic/claude-3.5-sonnet",
    "table_model": "anthropic/claude-3.5-sonnet",
    "image_model": "anthropic/claude-3.5-sonnet",
    "stamp_model": "anthropic/claude-3.5-sonnet"
  },
  "block_stats": {
    "total": 10,
    "text": 5,
    "image": 3,
    "stamp": 2,
    "processing_time_seconds": 120.5,
    "avg_time_per_block": 12.05
  },
  "r2_base_url": "https://...",
  "r2_files": [
    {"name": "document.pdf", "path": "document.pdf", "icon": "📄"}
  ]
}
```

### GET /jobs/{job_id}/progress

Прогресс с информацией о блоках.

**Ответ:**
```json
{
  "job_id": "uuid",
  "status": "processing",
  "progress": 75,
  "status_message": "Обработка блоков...",
  "phase_data": {...},
  "blocks": [...],
  "crops": [
    {"block_id": "XXXX-XXXX-XXX", "url": "https://...", "file_name": "block.png"}
  ]
}
```

### GET /jobs/{job_id}/result

Ссылка на скачивание результата.

**Ответ:**
```json
{
  "download_url": "https://presigned-url...",
  "file_name": "result.zip"
}
```

**Ошибки:**
- `400` — Задача не завершена
- `404` — Результат не найден

### POST /jobs/{job_id}/start

Запуск задачи.

### POST /jobs/{job_id}/cancel

Отмена задачи.

### POST /jobs/{job_id}/restart

Перезапуск задачи.

### PATCH /jobs/{job_id}

Обновление задачи.

**Body:**
```json
{
  "task_name": "New name",
  "status": "draft"
}
```

### DELETE /jobs/{job_id}

Удаление задачи и связанных файлов.

---

## Tree API (`/api/tree`)

Работа с иерархией проектов.

### GET /api/tree/nodes/root

Корневые узлы (проекты).

**Ответ:**
```json
[
  {
    "id": "uuid",
    "parent_id": null,
    "node_type": "project",
    "name": "Project Name",
    "code": "PRJ001",
    "status": "active",
    "attributes": {},
    "sort_order": 0,
    "version": 1,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

### GET /api/tree/nodes/{node_id}

Получить узел по ID.

### GET /api/tree/nodes/{node_id}/children

Дочерние узлы.

### POST /api/tree/nodes

Создать узел.

**Body:**
```json
{
  "node_type": "folder",
  "name": "Folder Name",
  "parent_id": "uuid",
  "code": "FLD001",
  "attributes": {}
}
```

### PATCH /api/tree/nodes/{node_id}

Обновить узел.

**Body:**
```json
{
  "name": "New Name",
  "status": "archived",
  "attributes": {"key": "value"}
}
```

### DELETE /api/tree/nodes/{node_id}

Удалить узел.

### POST /api/tree/nodes/{node_id}/pdf-status

Обновить статус PDF документа.

**Body:**
```json
{
  "status": "annotated",
  "message": "Аннотирование завершено"
}
```

### GET /api/tree/nodes/{node_id}/files

Файлы узла.

**Query параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| file_type | string | Фильтр по типу (опционально) |

**Ответ:**
```json
[
  {
    "id": "uuid",
    "node_id": "uuid",
    "file_type": "pdf",
    "r2_key": "n/{node_id}/document.pdf",
    "file_name": "document.pdf",
    "file_size": 1024000,
    "mime_type": "application/pdf",
    "metadata": {},
    "created_at": "..."
  }
]
```

### POST /api/tree/nodes/{node_id}/files

Добавить файл к узлу.

**Body:**
```json
{
  "file_type": "pdf",
  "r2_key": "n/{node_id}/document.pdf",
  "file_name": "document.pdf",
  "file_size": 1024000,
  "mime_type": "application/pdf",
  "metadata": {}
}
```

### DELETE /api/tree/files/{file_id}

Удалить файл узла.

### GET /api/tree/stage-types

Типы стадий.

### GET /api/tree/section-types

Типы разделов.

### GET /api/tree/image-categories

Категории изображений.

**Ответ:**
```json
[
  {
    "id": "uuid",
    "name": "Штамп",
    "code": "stamp",
    "description": "Печати и штампы",
    "system_prompt": "...",
    "user_prompt": "...",
    "is_default": false,
    "sort_order": 1
  }
]
```

### GET /api/tree/image-categories/code/{code}

Категория по коду.

---

## Storage API (`/api/storage`)

Операции с R2 хранилищем.

### GET /api/storage/exists/{r2_key}

Проверить существование объекта.

**Ответ:**
```json
{"exists": true}
```

### GET /api/storage/download/{r2_key}

Скачать файл (редирект на presigned URL).

### GET /api/storage/download-text/{r2_key}

Скачать текстовый файл.

**Ответ:**
```json
{"content": "file content..."}
```

### POST /api/storage/upload/{r2_key}

Загрузить файл (multipart/form-data).

**Ответ:**
```json
{"ok": true, "r2_key": "path/to/file"}
```

### POST /api/storage/upload-text

Загрузить текстовый контент.

**Body:**
```json
{
  "content": "text content",
  "r2_key": "path/to/file.txt",
  "content_type": "text/plain"
}
```

### DELETE /api/storage/delete/{r2_key}

Удалить объект.

### DELETE /api/storage/delete-prefix/{prefix}

Удалить все объекты с префиксом.

**Ответ:**
```json
{
  "deleted_count": 5,
  "error_count": 0,
  "deleted": ["key1", "key2", ...]
}
```

### POST /api/storage/delete-batch

Удалить несколько объектов.

**Body:**
```json
{"keys": ["key1", "key2"]}
```

**Ответ:**
```json
{
  "deleted": ["key1"],
  "errors": ["key2"]
}
```

### GET /api/storage/list/{prefix}

Список файлов по префиксу.

**Ответ:**
```json
["path/file1.pdf", "path/file2.json"]
```

### GET /api/storage/list-metadata/{prefix}

Список файлов с метаданными.

**Ответ:**
```json
[
  {
    "key": "path/file.pdf",
    "size": 1024000,
    "last_modified": "2024-01-01T00:00:00Z",
    "content_type": null
  }
]
```

---

## Коды ошибок

| Код | Описание |
|-----|----------|
| 400 | Ошибка валидации параметров |
| 401 | Неверный или отсутствующий X-API-Key |
| 404 | Ресурс не найден |
| 500 | Внутренняя ошибка сервера |
| 503 | Очередь переполнена |

---

## Примеры curl

### Health check
```bash
curl http://localhost:18000/health
```

### Список задач
```bash
curl -H "X-API-Key: YOUR_KEY" http://localhost:18000/jobs
```

### Инициализация задачи
```bash
curl -X POST http://localhost:18000/jobs/init \
  -H "X-API-Key: YOUR_KEY" \
  -F "client_id=client-123" \
  -F "document_id=doc-456" \
  -F "document_name=document.pdf" \
  -F "node_id=node-789" \
  -F "pdf_size=1024000" \
  -F "blocks_size=5000" \
  -F "engine=openrouter"
```

### Скачать результат
```bash
curl -H "X-API-Key: YOUR_KEY" \
  http://localhost:18000/jobs/{job_id}/result
```
