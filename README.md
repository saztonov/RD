# PDF Annotation Tool

Desktop-клиент для аннотирования PDF с удалённым OCR и управлением проектами.

## Функциональность

- ✅ Просмотр PDF, ручное выделение блоков (text/table/image)
- ✅ Полигональная разметка (произвольные фигуры)
- ✅ **Remote OCR** — Celery + Redis очередь, FastAPI + R2
- ✅ **Tree Projects** — иерархия проектов в Supabase
- ✅ Двухпроходный алгоритм OCR (экономия памяти)
- ✅ Сохранение/загрузка разметки (JSON + R2)
- ✅ Undo/Redo, навигация, зум
- ✅ Экспорт кропов (PDF) и Markdown
- ✅ Редактируемые промпты OCR (R2 Storage)
- ✅ Настройки OCR из Supabase (app_settings)

## Установка

### 1. Python 3.11+

```bash
pip install -r requirements.txt
```

### 2. .env (опционально)

```bash
# Remote OCR сервер
REMOTE_OCR_BASE_URL=http://localhost:8000
REMOTE_OCR_API_KEY=

# Tree Projects (Supabase)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key

# OCR движки
OPENROUTER_API_KEY=your_key
DATALAB_API_KEY=your_key

# R2 Storage
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=rd1
R2_PUBLIC_URL=https://pub-xxxxx.r2.dev
```

## Запуск

### Клиент (Desktop)

```bash
python app/main.py
```

### Remote OCR сервер

**Docker (рекомендуется):**
```bash
docker compose -f docker-compose.remote-ocr.dev.yml up --build
```

Запускает 3 сервиса:
- `web` — FastAPI сервер (порт 8000)
- `redis` — Redis для Celery
- `worker` — Celery воркер

**Без Docker:**
```bash
# Терминал 1: Redis
redis-server

# Терминал 2: API сервер
cd services/remote_ocr
uvicorn services.remote_ocr.server.main:app --host 0.0.0.0 --port 8000 --reload

# Терминал 3: Celery воркер
celery -A services.remote_ocr.server.celery_app worker --loglevel=info --concurrency=1
```

**Проверка:**
```bash
curl http://localhost:8000/health
curl http://localhost:8000/queue
```

## Структура проекта

```
RD/
├── app/
│   ├── main.py                    # Точка входа
│   ├── remote_ocr_client.py       # HTTP-клиент для Remote OCR
│   ├── tree_client.py             # Клиент для Supabase (Tree Projects)
│   └── gui/
│       ├── main_window.py         # Главное окно (миксины)
│       ├── menu_setup.py          # Меню
│       ├── panels_setup.py        # Панели
│       ├── page_viewer*.py        # Просмотр PDF (polygon/resize/blocks)
│       ├── remote_ocr_panel.py    # Панель Remote OCR
│       ├── project_tree_widget.py # Дерево проектов
│       ├── blocks_tree_manager.py # Дерево блоков
│       ├── prompt_manager.py      # Менеджер промптов
│       ├── navigation_manager.py  # Навигация + зум
│       ├── file_operations.py     # Файловые операции
│       ├── block_handlers.py      # Обработка блоков
│       ├── tree_node_operations.py # CRUD узлов дерева
│       ├── file_transfer_worker.py # Загрузка файлов в R2
│       └── *_dialog.py            # Диалоги
├── rd_core/
│   ├── models.py                  # Block, Document, Page
│   ├── pdf_utils.py               # PyMuPDF
│   ├── annotation_io.py           # JSON I/O
│   ├── r2_storage.py              # R2 Storage клиент (sync)
│   └── ocr/
│       ├── base.py                # OCRBackend абстракция
│       ├── openrouter.py          # OpenRouter API
│       ├── datalab.py             # Datalab API
│       ├── dummy.py               # Заглушка
│       ├── factory.py             # create_ocr_engine()
│       └── markdown_generator.py  # Генерация MD
├── services/remote_ocr/
│   ├── server/
│   │   ├── main.py                # FastAPI приложение
│   │   ├── celery_app.py          # Celery конфигурация
│   │   ├── tasks.py               # Celery задачи (run_ocr_task)
│   │   ├── storage.py             # DB (Supabase)
│   │   ├── settings.py            # Настройки (из Supabase/env)
│   │   ├── rate_limiter.py        # Rate limiting
│   │   ├── queue_checker.py       # Backpressure
│   │   ├── async_r2_storage.py    # R2 (async)
│   │   ├── pdf_streaming*.py      # Streaming OCR обработка
│   │   ├── worker_*.py            # Worker утилиты
│   │   ├── memory_utils.py        # Мониторинг памяти
│   │   └── routes/
│   │       ├── jobs.py            # /jobs API
│   │       └── common.py          # Общие функции
│   ├── Dockerfile
│   └── requirements.txt
├── database/migrations/
│   └── prod.sql                   # Миграции Supabase
├── docker-compose.remote-ocr.dev.yml
├── requirements.txt
└── README.md
```

## Архитектура

### Remote OCR

**Клиент** → **FastAPI** → **Celery + Redis** → **Worker** → **R2 Storage**

- **Создание задачи:** PDF + блоки → загрузка в R2 → запись в Supabase → Celery задача
- **Обработка:** Worker скачивает из R2 → двухпроходный OCR → результат в R2
- **Результат:** Markdown + annotation.json + кропы (PDF)

**Статусы:** `draft` | `queued` | `processing` | `done` | `error` | `paused`

**API ключ:** опциональный (`X-API-Key` header)

**Backpressure:** `/queue` endpoint, лимит очереди (MAX_QUEUE_SIZE)

### Двухпроходный алгоритм OCR

1. **Pass 1:** Рендер PDF → кропы на диск (экономия RAM)
2. **Pass 2:** Загрузка кропов по одному → OCR → результат

Настройка: `USE_TWO_PASS_OCR=true` (по умолчанию)

### Tree Projects

Иерархия проектов в Supabase:

```
PROJECT
└── STAGE (стадия)
    └── SECTION (раздел)
        └── TASK_FOLDER (папка заданий)
            └── DOCUMENT (документ)
```

- **Версионирование:** автоматическое (v1, v2, ...)
- **Lazy Loading:** дочерние узлы подгружаются при раскрытии
- **client_id:** уникальный ID клиента (`~/.config/RD/client_id.txt`)
- **node_files:** связь файлов с узлами (PDF, annotation, result_md, crop)

### GUI (PySide6)

**Миксины:**
- `MenuSetupMixin` — меню
- `PanelsSetupMixin` — панели (блоки, проекты)
- `FileOperationsMixin` — открытие/сохранение PDF
- `BlockHandlersMixin` — добавление/удаление блоков

**Менеджеры:**
- `NavigationManager` — навигация по страницам, зум
- `BlocksTreeManager` — дерево блоков на странице
- `PromptManager` — загрузка/синхронизация промптов из R2

**Панели:**
- `RemoteOCRPanel` — управление задачами OCR
- `ProjectTreeWidget` — дерево проектов (Supabase)

## Использование

### 1. Открытие PDF

`File → Open PDF` → выбрать файл

### 2. Разметка блоков

- Прямоугольники: рисуйте мышью
- Полигоны: `Ctrl+P` для переключения режима
- Тип блока: text/table/image

### 3. Remote OCR

1. Выделите блоки → `Remote OCR → Send to OCR`
2. Выберите движок (`openrouter`/`datalab`) и модели
3. Отслеживайте прогресс в панели Remote OCR
4. Результат автоматически сохраняется в R2

### 4. Tree Projects

1. `View → Tree Projects` — открыть панель
2. Создавайте иерархию: PROJECT → STAGE → SECTION → TASK_FOLDER
3. Добавляйте документы в TASK_FOLDER
4. Версионирование автоматическое

### 5. Промпты OCR

`Settings → Edit Prompts` → редактирование промптов (загружаются из R2)

### 6. Сохранение разметки

- `File → Save Annotation` → сохранить JSON локально
- `File → Save Draft to Server` → сохранить PDF + разметка на сервере (без OCR)

## API

### Remote OCR Client

```python
from app.remote_ocr_client import RemoteOCRClient

client = RemoteOCRClient()

# Создать задачу
job = client.create_job(
    pdf_path="doc.pdf",
    selected_blocks=blocks,
    task_name="My Task",
    engine="openrouter",
    text_model="qwen/qwen3-vl-30b-a3b-instruct",
    node_id="optional-tree-node-id"
)

# Проверить статус
job = client.get_job(job.id)

# Скачать результат (когда done)
client.download_result(job.id, "result.zip")

# Управление задачей
client.pause_job(job.id)
client.resume_job(job.id)
client.restart_job(job.id)
client.delete_job(job.id)
```

### Tree Client

```python
from app.tree_client import TreeClient, NodeType, FileType

client = TreeClient()

# Создать проект
project = client.create_node(NodeType.PROJECT, "My Project")

# Создать стадию
stage = client.create_node(NodeType.STAGE, "П", parent_id=project.id, code="P")

# Добавить документ
doc = client.add_document(
    parent_id=task_folder.id,
    name="doc.pdf",
    r2_key="tree_docs/node_id/doc.pdf",
    file_size=1024
)

# Получить файлы узла
files = client.get_node_files(doc.id, file_type=FileType.PDF)

# Lazy loading
children = client.get_children(project.id)
```

### Models

```python
from rd_core.models import Block, BlockType, BlockSource, ShapeType

# Создать блок
block = Block.create(
    page_index=0,
    coords_px=(100, 100, 500, 500),
    page_width=1600,
    page_height=2400,
    block_type=BlockType.TEXT,
    source=BlockSource.USER,
    shape_type=ShapeType.RECTANGLE
)

# Полигон
polygon_block = Block.create(
    page_index=0,
    coords_px=(100, 100, 500, 500),
    page_width=1600,
    page_height=2400,
    block_type=BlockType.TABLE,
    source=BlockSource.USER,
    shape_type=ShapeType.POLYGON,
    polygon_points=[(100, 100), (500, 100), (500, 500), (100, 500)]
)
```

### OCR Engine

```python
from rd_core.ocr import create_ocr_engine

# OpenRouter
backend = create_ocr_engine(
    "openrouter",
    api_key="your_key",
    model_name="qwen/qwen3-vl-30b-a3b-instruct"
)

# Datalab
backend = create_ocr_engine(
    "datalab",
    api_key="your_key"
)

# Распознать
text = backend.recognize(image, prompt={"system": "...", "user": "..."})
```

## Настройки сервера

Настройки загружаются из Supabase (`app_settings`) или env:

| Параметр | Env | Default | Описание |
|----------|-----|---------|----------|
| max_concurrent_jobs | MAX_CONCURRENT_JOBS | 4 | Макс. параллельных задач |
| ocr_threads_per_job | OCR_THREADS_PER_JOB | 2 | OCR потоков на задачу |
| max_global_ocr_requests | MAX_GLOBAL_OCR_REQUESTS | 8 | Глобальный лимит OCR |
| use_two_pass_ocr | USE_TWO_PASS_OCR | true | Двухпроходный алгоритм |
| pdf_render_dpi | PDF_RENDER_DPI | 300 | DPI рендера PDF |
| max_queue_size | MAX_QUEUE_SIZE | 100 | Лимит очереди |
| datalab_max_rpm | DATALAB_MAX_RPM | 180 | Datalab rate limit |

## Сборка в EXE

```bash
python build.py
```

Результат: `dist/PDFAnnotation.exe`

## Документация

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — полная техническая документация
- [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) — руководство разработчика
- [`docs/GUI_COMPONENTS.md`](docs/GUI_COMPONENTS.md) — компоненты GUI
- [`docs/DATABASE.md`](docs/DATABASE.md) — схема базы данных (Supabase)
- [`docs/REMOTE_OCR_SERVER.md`](docs/REMOTE_OCR_SERVER.md) — Remote OCR сервер
- [`docs/R2_STORAGE_INTEGRATION.md`](docs/R2_STORAGE_INTEGRATION.md) — R2 Storage
- [`docs/PROMPTS_R2_INTEGRATION.md`](docs/PROMPTS_R2_INTEGRATION.md) — промпты
- [`ЗАПУСК.md`](ЗАПУСК.md) — команды запуска

## Логирование

- **Файл:** `logs/app.log`
- **Уровень:** `logging.INFO` (по умолчанию)
- **DEBUG:** измените в `app/main.py`

```python
setup_logging(log_level=logging.DEBUG)
```

---

**Python:** 3.11+  
**GUI:** PySide6  
**Storage:** Cloudflare R2 + Supabase  
**OCR:** OpenRouter, Datalab  
**Queue:** Celery + Redis
