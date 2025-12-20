# PDF Annotation Tool

Desktop-клиент для аннотирования PDF с удалённым OCR и управлением проектами.

## Функциональность

- ✅ Просмотр PDF, ручное выделение блоков (text/table/image)
- ✅ **Remote OCR** — отправка задач на удалённый сервер (FastAPI + R2)
- ✅ **Tree Projects** — иерархия проектов в Supabase
- ✅ Сохранение/загрузка разметки (JSON + R2)
- ✅ Undo/Redo, навигация, зум
- ✅ Экспорт кропов и Markdown
- ✅ Редактируемые промпты OCR (R2 Storage)

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

### Remote OCR сервер (опционально)

**Docker:**
```bash
docker compose -f docker-compose.remote-ocr.dev.yml up --build
```

**Без Docker:**
```bash
cd services/remote_ocr
uvicorn services.remote_ocr.server.main:app --host 0.0.0.0 --port 8000 --reload
```

**Проверка:**
```bash
curl http://localhost:8000/health
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
│       ├── page_viewer*.py        # Просмотр PDF (polygon/resize)
│       ├── remote_ocr_panel.py    # Панель Remote OCR
│       ├── project_tree_widget.py # Дерево проектов
│       ├── blocks_tree_manager.py # Дерево блоков
│       ├── prompt_manager.py      # Менеджер промптов
│       ├── navigation_manager.py  # Навигация + зум
│       ├── file_operations.py     # Файловые операции
│       ├── block_handlers.py      # Обработка блоков
│       ├── *_dialog.py            # Диалоги
│       └── utils.py
├── rd_core/
│   ├── models.py                  # Block, Document, PageModel
│   ├── pdf_utils.py               # PyMuPDF
│   ├── annotation_io.py           # JSON I/O
│   ├── cropping.py                # Кропы блоков
│   ├── ocr.py                     # OCR движки
│   └── r2_storage.py              # R2 Storage клиент
├── services/remote_ocr/
│   ├── server/
│   │   ├── main.py                # FastAPI сервер
│   │   ├── worker*.py             # Worker для OCR
│   │   ├── storage.py             # DB (Supabase)
│   │   ├── rate_limiter.py        # Rate limiting
│   │   └── settings.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── tree_schema.sql            # SQL schema для Supabase
├── database/migrations/
│   └── prod.sql                   # Миграции Supabase
├── docker-compose.remote-ocr.dev.yml
├── requirements.txt
└── README.md
```

## Архитектура

### Remote OCR

**Клиент** → **FastAPI сервер** → **Worker (очередь)** → **R2 Storage**

- **Создание задачи:** PDF + блоки → загрузка в R2 → запись в Supabase
- **Обработка:** Worker скачивает из R2 → OCR → результат в R2
- **Результат:** Markdown + кропы блоков (ZIP)

**Статусы:** `draft` | `queued` | `processing` | `done` | `error` | `paused`

**API ключ:** опциональный (`X-API-Key` header)

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
- **client_id:** уникальный ID клиента (хранится в `~/.config/RD/client_id.txt`)

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

Рисуйте прямоугольники на странице → выбирайте тип блока (text/table/image)

### 3. Remote OCR

1. Выделите блоки → `Remote OCR → Send to OCR`
2. Выберите движок (`openrouter`/`datalab`) и модели
3. Отслеживайте прогресс в панели Remote OCR
4. Скачайте результат (ZIP с Markdown + кропами)

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

## API для разработчиков

### Remote OCR Client

```python
from app.remote_ocr_client import RemoteOCRClient

client = RemoteOCRClient()

# Создать задачу
job = client.create_job(
    pdf_path="doc.pdf",
    selected_blocks=blocks,
    task_name="My Task",
    engine="openrouter"
)

# Проверить статус
job = client.get_job(job.id)

# Скачать результат (когда done)
client.download_result(job.id, "result.zip")
```

### Tree Client

```python
from app.tree_client import TreeClient, NodeType

client = TreeClient()

# Создать проект
project = client.create_node(NodeType.PROJECT, "My Project")

# Создать стадию
stage = client.create_node(NodeType.STAGE, "П", parent_id=project.id, code="P")

# Lazy loading
children = client.get_children(project.id)
```

### PDF + Модели

```python
from rd_core.pdf_utils import PDFDocument
from rd_core.models import Block, BlockType

# Открыть PDF
doc = PDFDocument("doc.pdf")

# Создать блок
block = Block.create(
    page_index=0,
    coords_px=(100, 100, 500, 500),
    page_width=1600,
    page_height=2400,
    block_type=BlockType.TEXT
)

doc.close()
```

## Сборка в EXE

```bash
python build.py
```

Результат: `dist/PDFAnnotation.exe`

## Документация

- [`ЗАПУСК.md`](ЗАПУСК.md) — команды запуска
- [`docs/R2_STORAGE_INTEGRATION.md`](docs/R2_STORAGE_INTEGRATION.md) — R2 Storage
- [`docs/PROMPTS_R2_INTEGRATION.md`](docs/PROMPTS_R2_INTEGRATION.md) — промпты

## Логирование

- **Файл:** `logs/app.log`
- **Уровень:** `logging.INFO` (по умолчанию)
- **DEBUG:** измените в `app/main.py`

```python
setup_logging(log_level=logging.DEBUG)
```

---

**Python:** 3.11  
**GUI:** PySide6  
**Storage:** Cloudflare R2 + Supabase  
**OCR:** OpenRouter, Datalab
