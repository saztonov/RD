# Remote OCR Server

## Обзор

Remote OCR Server — FastAPI сервер для распределённой обработки OCR-задач.

### Компоненты

```
┌──────────────────────────────────────────────────────────┐
│                     Remote OCR Server                     │
├────────────────┬───────────────────┬─────────────────────┤
│                │                   │                     │
│   FastAPI      │   Celery Worker   │      Redis          │
│   (API)        │   (OCR Tasks)     │      (Queue)        │
│                │                   │                     │
└───────┬────────┴─────────┬─────────┴──────────┬──────────┘
        │                  │                    │
        ▼                  ▼                    │
┌───────────────┐  ┌───────────────┐           │
│   Supabase    │  │  R2 Storage   │◄──────────┘
│   (Database)  │  │  (Files)      │
└───────────────┘  └───────────────┘
```

---

## Быстрый старт

### Docker (рекомендуется)

```bash
docker compose -f docker-compose.remote-ocr.dev.yml up --build
```

### Без Docker

```bash
# Terminal 1: Redis
redis-server

# Terminal 2: API
cd services/remote_ocr
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 3: Worker
cd services/remote_ocr
celery -A server.celery_app worker -l info
```

### Проверка

```bash
curl http://localhost:8000/health
# {"ok": true}
```

---

## Конфигурация

### Environment Variables

```env
# Обязательные
SUPABASE_URL=https://project.supabase.co
SUPABASE_KEY=your_anon_key
REDIS_URL=redis://localhost:6379/0

# R2 Storage
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=rd1
R2_PUBLIC_URL=https://pub-xxxxx.r2.dev

# OCR API Keys
OPENROUTER_API_KEY=sk-or-...
DATALAB_API_KEY=...

# Опциональные
REMOTE_OCR_API_KEY=        # Если задан — требуется X-API-Key
REMOTE_OCR_DATA_DIR=/data  # Директория для временных файлов

# Лимиты
MAX_CONCURRENT_JOBS=2      # Параллельных задач
DATALAB_MAX_RPM=180        # Запросов в минуту к Datalab
DATALAB_MAX_CONCURRENT=5   # Параллельных запросов к Datalab
POLL_INTERVAL=10           # Интервал polling очереди (сек)
```

### settings.py

```python
@dataclass(frozen=True)
class Settings:
    data_dir: str = os.getenv("REMOTE_OCR_DATA_DIR", "/data")
    api_key: str = os.getenv("REMOTE_OCR_API_KEY", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    datalab_api_key: str = os.getenv("DATALAB_API_KEY", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    datalab_max_rpm: int = 180
    datalab_max_concurrent: int = 5
    max_concurrent_jobs: int = 2
    poll_interval: float = 10
```

---

## API Endpoints

### Health Check

```
GET /health
Response: {"ok": true}
```

---

### Jobs

#### Создать задачу

```
POST /jobs
Content-Type: multipart/form-data
X-API-Key: optional_key

Form fields:
  client_id: string (required)
  document_id: string (SHA256 хеш PDF)
  document_name: string
  task_name: string
  engine: string (openrouter|datalab)
  text_model: string
  table_model: string
  image_model: string

Files:
  pdf: application/pdf
  blocks_file: application/json

Response 200:
{
  "id": "uuid",
  "status": "queued",
  "progress": 0,
  "document_id": "sha256...",
  "document_name": "file.pdf",
  "task_name": "My Task"
}
```

#### Создать черновик

```
POST /jobs/draft
Content-Type: multipart/form-data

Form fields:
  client_id: string
  document_id: string
  document_name: string
  task_name: string
  annotation_json: string (JSON Document)

Files:
  pdf: application/pdf

Response 200:
{
  "id": "uuid",
  "status": "draft",
  ...
}
```

#### Запустить черновик

```
POST /jobs/{job_id}/start
Content-Type: application/x-www-form-urlencoded

Body:
  engine=openrouter
  text_model=qwen/qwen3-vl-30b
  table_model=
  image_model=

Response 200:
{"ok": true, "job_id": "uuid", "status": "queued"}
```

#### Список задач

```
GET /jobs
Query params:
  client_id: string (optional)
  document_id: string (optional)

Response 200:
[
  {
    "id": "uuid",
    "status": "done",
    "progress": 1.0,
    "document_name": "file.pdf",
    "task_name": "Task 1",
    "document_id": "sha256...",
    "created_at": "2025-01-20T12:00:00Z",
    "updated_at": "2025-01-20T12:30:00Z",
    "error_message": null
  },
  ...
]
```

#### Получить задачу

```
GET /jobs/{job_id}

Response 200:
{
  "id": "uuid",
  "client_id": "xxx",
  "document_id": "sha256...",
  "document_name": "file.pdf",
  "task_name": "Task 1",
  "status": "done",
  "progress": 1.0,
  "engine": "openrouter",
  "r2_prefix": "ocr_jobs/uuid",
  "error_message": null,
  "created_at": "...",
  "updated_at": "..."
}
```

#### Детали задачи

```
GET /jobs/{job_id}/details

Response 200:
{
  ...JobInfo,
  "block_stats": {
    "total": 15,
    "text": 8,
    "table": 5,
    "image": 2,
    "grouped": 13
  },
  "job_settings": {
    "text_model": "qwen/qwen3-vl-30b",
    "table_model": "",
    "image_model": ""
  },
  "r2_base_url": "https://pub-xxx.r2.dev/ocr_jobs/uuid",
  "r2_files": [
    {"name": "document.pdf", "path": "document.pdf", "icon": "📄"},
    {"name": "blocks.json", "path": "blocks.json", "icon": "📋"},
    {"name": "result.md", "path": "result.md", "icon": "📝"},
    {"name": "result.zip", "path": "result.zip", "icon": "📦"}
  ]
}
```

#### Скачать результат

```
GET /jobs/{job_id}/result

Response 200:
{
  "download_url": "https://xxx.r2.dev/...",
  "file_name": "result.zip"
}

Response 400:
{"detail": "Job not ready, status: processing"}

Response 404:
{"detail": "Result file not found"}
```

#### Управление

```
# Обновить название
PATCH /jobs/{job_id}
Body: task_name=New Name
Response: {"ok": true}

# Пауза
POST /jobs/{job_id}/pause
Response: {"ok": true, "status": "paused"}

# Возобновление
POST /jobs/{job_id}/resume
Response: {"ok": true, "status": "queued"}

# Перезапуск
POST /jobs/{job_id}/restart
Response: {"ok": true, "status": "queued"}

# Удаление
DELETE /jobs/{job_id}
Response: {"ok": true, "deleted_job_id": "uuid"}
```

---

## Celery Worker

### Конфигурация (celery_app.py)

```python
from celery import Celery

celery_app = Celery(
    "remote_ocr",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 час max
    worker_prefetch_multiplier=1,
)
```

### Основная задача (tasks.py)

```python
@celery_app.task(bind=True, name="run_ocr_task", max_retries=3)
def run_ocr_task(self, job_id: str) -> dict:
    """
    Обработка OCR-задачи:
    1. Скачать PDF и blocks.json из R2
    2. Вырезать кропы блоков
    3. Группировка TEXT/TABLE в полосы
    4. OCR для полос через выбранный движок
    5. OCR для IMAGE блоков
    6. Генерация result.md и annotation.json
    7. Создание result.zip
    8. Загрузка результатов в R2
    9. Обновление статуса в Supabase
    """
```

### Этапы обработки

1. **Инициализация** (progress: 0.05)
   - Получение задачи из Supabase
   - Проверка на паузу
   - Создание временной директории

2. **Скачивание файлов** (progress: 0.10)
   - PDF из R2
   - blocks.json из R2

3. **Кропы блоков** (progress: 0.10-0.20)
   - Рендеринг страниц
   - Вырезание кропов
   - Группировка в полосы

4. **OCR обработка** (progress: 0.20-0.90)
   - TEXT/TABLE полосы
   - IMAGE блоки (индивидуально)
   - Параллельное выполнение (ThreadPoolExecutor)

5. **Генерация результатов** (progress: 0.90-0.95)
   - result.md (Markdown)
   - annotation.json (полная разметка)
   - result.zip (архив)

6. **Загрузка в R2** (progress: 0.95-1.0)
   - result.md
   - annotation.json
   - result.zip
   - crops/*.pdf

7. **Завершение**
   - update_job_status(done)
   - Очистка temp директории

### Обработка ошибок

```python
try:
    # ... обработка
except Exception as e:
    update_job_status(job_id, "error", error_message=str(e))
    return {"status": "error", "message": str(e)}
finally:
    # Очистка temp
    if work_dir and work_dir.exists():
        shutil.rmtree(work_dir)
```

---

## Rate Limiter

### Datalab API Limiter

```python
# rate_limiter.py
class DatalabRateLimiter:
    """
    Rate limiter для Datalab API:
    - max_rpm: запросов в минуту
    - max_concurrent: параллельных запросов
    """
    
    def acquire(self, timeout: float = 60.0) -> bool:
        """Получить разрешение на запрос"""
        
    def release(self):
        """Освободить слот"""

# Использование
limiter = get_datalab_limiter()
if limiter.acquire():
    try:
        result = datalab_api.recognize(image)
    finally:
        limiter.release()
```

---

## Storage (Supabase)

### CRUD операции

```python
# storage.py

def create_job(...) -> Job:
    """Создать задачу в Supabase"""

def get_job(job_id, with_files=False, with_settings=False) -> Job:
    """Получить задачу"""

def list_jobs(client_id=None, document_id=None) -> List[Job]:
    """Список задач"""

def update_job_status(job_id, status, progress=None, error_message=None):
    """Обновить статус"""

def claim_next_job(max_concurrent=2) -> Optional[Job]:
    """Атомарно взять следующую задачу из очереди"""

def pause_job(job_id) -> bool:
    """Поставить на паузу"""

def resume_job(job_id) -> bool:
    """Возобновить"""

def delete_job(job_id) -> bool:
    """Удалить (каскадно)"""
```

### Job Files

```python
def add_job_file(job_id, file_type, r2_key, file_name, file_size) -> JobFile:
    """Добавить запись о файле"""

def get_job_files(job_id, file_type=None) -> List[JobFile]:
    """Получить файлы задачи"""

def get_job_file_by_type(job_id, file_type) -> Optional[JobFile]:
    """Получить файл по типу"""

def delete_job_files(job_id, file_types=None) -> int:
    """Удалить записи о файлах"""
```

### Job Settings

```python
def save_job_settings(job_id, text_model, table_model, image_model):
    """Сохранить/обновить настройки (upsert)"""

def get_job_settings(job_id) -> Optional[JobSettings]:
    """Получить настройки"""
```

---

## Worker Prompts

### Промпты для TEXT/TABLE

```python
def build_strip_prompt(blocks: List[Block]) -> dict:
    """
    Построить промпт для batch-распознавания полосы.
    Нумерует блоки для парсинга ответа.
    """
    return {
        "system": "...",
        "user": "Блок 1:\n...\nБлок 2:\n..."
    }
```

### Промпты для IMAGE

```python
def fill_image_prompt_variables(prompt_data, doc_name, page_index, 
                                 block_id, hint, pdfplumber_text) -> dict:
    """
    Заполнить placeholder-переменные в промпте:
    {{doc_name}}, {{page_index}}, {{block_id}}, {{hint}}, {{pdfplumber_text}}
    """
```

### Парсинг ответов

```python
def parse_batch_response_by_index(num_blocks: int, response_text: str) -> dict:
    """
    Парсинг batch-ответа с нумерацией:
    "Блок 1: текст...\nБлок 2: текст..."
    → {0: "текст...", 1: "текст..."}
    """
```

---

## Docker Compose

### Development

```yaml
# docker-compose.remote-ocr.dev.yml
version: "3.8"

services:
  api:
    build:
      context: .
      dockerfile: services/remote_ocr/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - DATALAB_API_KEY=${DATALAB_API_KEY}
      - R2_ACCOUNT_ID=${R2_ACCOUNT_ID}
      - R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID}
      - R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY}
      - R2_BUCKET_NAME=${R2_BUCKET_NAME}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    volumes:
      - ./services/remote_ocr:/app
    command: uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

  worker:
    build:
      context: .
      dockerfile: services/remote_ocr/Dockerfile
    environment:
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - DATALAB_API_KEY=${DATALAB_API_KEY}
      - R2_ACCOUNT_ID=${R2_ACCOUNT_ID}
      - R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID}
      - R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY}
      - R2_BUCKET_NAME=${R2_BUCKET_NAME}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
      - api
    volumes:
      - ./services/remote_ocr:/app
    command: celery -A server.celery_app worker -l info

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Системные зависимости для PyMuPDF
RUN apt-get update && apt-get install -y \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY services/remote_ocr/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/remote_ocr/ .
COPY rd_core/ /app/rd_core/

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Мониторинг

### Логирование

```python
import logging
logger = logging.getLogger(__name__)

# В задаче
logger.info(f"[CELERY] Начало обработки задачи {job_id}")
logger.debug(f"Задача {job.id}: {len(blocks)} блоков")
logger.error(f"Ошибка OCR для блока {block.id}: {e}", exc_info=True)
```

### Celery Flower (опционально)

```bash
pip install flower
celery -A server.celery_app flower --port=5555
# UI: http://localhost:5555
```

### Prometheus метрики (опционально)

```python
from prometheus_client import Counter, Histogram

jobs_total = Counter('ocr_jobs_total', 'Total OCR jobs', ['status'])
job_duration = Histogram('ocr_job_duration_seconds', 'Job duration')

# В задаче
with job_duration.time():
    process_job(...)
jobs_total.labels(status='done').inc()
```

---

## Troubleshooting

### Worker не стартует

```bash
# Проверить Redis
redis-cli ping

# Проверить подключение к Supabase
python -c "
from server.storage import init_db
init_db()
"

# Запустить с debug
celery -A server.celery_app worker -l debug
```

### Задачи зависают в queued

```bash
# Проверить воркер
celery -A server.celery_app inspect active

# Проверить очередь
celery -A server.celery_app inspect reserved

# Принудительно очистить очередь
celery -A server.celery_app purge
```

### Ошибки R2

```python
# Проверить подключение
from rd_core.r2_storage import R2Storage
r2 = R2Storage()
print(r2.list_objects(prefix="test/"))
```

### Memory issues

```bash
# Увеличить лимит для воркера
celery -A server.celery_app worker --max-memory-per-child=500000
```

---

## Масштабирование

### Горизонтальное

```yaml
# docker-compose.yml
services:
  worker:
    deploy:
      replicas: 3
```

### Вертикальное

```env
# Больше параллельных задач
MAX_CONCURRENT_JOBS=5
DATALAB_MAX_CONCURRENT=10
```

### Redis Cluster

```env
REDIS_URL=redis://redis-cluster:6379/0
```

