# PDF Annotation Tool — Техническая документация

## Оглавление

1. [Обзор системы](#обзор-системы)
2. [Архитектура](#архитектура)
3. [Модели данных](#модели-данных)
4. [Desktop-клиент (GUI)](#desktop-клиент-gui)
5. [Remote OCR Server](#remote-ocr-server)
6. [Tree Projects (Supabase)](#tree-projects-supabase)
7. [Хранилище R2](#хранилище-r2)
8. [OCR движки](#ocr-движки)
9. [API Reference](#api-reference)
10. [База данных](#база-данных)
11. [Развёртывание](#развёртывание)

---

## Обзор системы

**PDF Annotation Tool** — desktop-приложение для аннотирования PDF-документов с поддержкой:

- **Ручной разметки**: рисование прямоугольников и полигонов на страницах PDF
- **Remote OCR**: отправка PDF на удалённый сервер для распознавания
- **Tree Projects**: иерархическое управление проектами через Supabase
- **R2 Storage**: хранение файлов и результатов в Cloudflare R2

### Технологический стек

| Компонент | Технология |
|-----------|------------|
| GUI | PySide6 (Qt 6) |
| PDF | PyMuPDF (fitz) |
| OCR | OpenRouter API, Datalab API |
| Storage | Cloudflare R2 (S3-совместимое) |
| Database | Supabase (PostgreSQL) |
| Queue | Celery + Redis |
| Server | FastAPI + Uvicorn |
| Container | Docker Compose |

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DESKTOP CLIENT                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │  MainWindow  │  │  PageViewer  │  │  ProjectTreeWidget       │   │
│  │  (Mixins)    │  │  (PDF View)  │  │  (Supabase Tree)         │   │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘   │
│         │                 │                        │                 │
│  ┌──────┴─────────────────┴────────────────────────┴──────────────┐ │
│  │                      Managers & Clients                         │ │
│  │  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │ │
│  │  │ RemoteOCRClient │ │   TreeClient    │ │  PromptManager  │   │ │
│  │  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘   │ │
│  └───────────┼───────────────────┼───────────────────┼────────────┘ │
└──────────────┼───────────────────┼───────────────────┼──────────────┘
               │                   │                   │
               ▼                   ▼                   ▼
┌──────────────────────┐  ┌──────────────┐  ┌──────────────────────┐
│   REMOTE OCR SERVER  │  │   SUPABASE   │  │      R2 STORAGE      │
│  ┌────────────────┐  │  │  (PostgreSQL)│  │   (Cloudflare R2)    │
│  │    FastAPI     │  │  │              │  │                      │
│  └───────┬────────┘  │  │  - tree_nodes│  │  - prompts/          │
│          │           │  │  - jobs      │  │  - ocr_jobs/         │
│  ┌───────┴────────┐  │  │  - job_files │  │  - ocr_results/      │
│  │  Celery Worker │  │  │  - stage_typ │  │                      │
│  └───────┬────────┘  │  │  - section_ty│  │                      │
│          │           │  └──────────────┘  └──────────────────────┘
│  ┌───────┴────────┐  │
│  │     Redis      │  │
│  └────────────────┘  │
└──────────────────────┘
```

### Потоки данных

#### 1. Создание OCR-задачи

```
1. Пользователь выделяет блоки в PageViewer
2. MainWindow → RemoteOCRPanel._create_job()
3. RemoteOCRClient.create_job() → POST /jobs
4. Server: PDF + blocks.json → R2 Storage
5. Server: Job record → Supabase (status=queued)
6. Celery: run_ocr_task.delay(job_id)
7. Worker: скачивает PDF из R2 → OCR → result.zip → R2
8. Worker: update_job_status(done)
9. Client polling → обновление UI
```

#### 2. Tree Projects

```
1. ProjectTreeWidget.client = TreeClient()
2. client.get_root_nodes() → Supabase REST API
3. Lazy loading: itemExpanded → client.get_children()
4. Контекстное меню → create/rename/delete node
```

---

## Модели данных

### rd_core/models.py

#### Block

Основная единица разметки — блок на странице PDF.

```python
@dataclass
class Block:
    id: str                           # UUID блока
    page_index: int                   # Номер страницы (0-based)
    coords_px: Tuple[int, int, int, int]    # Координаты в пикселях (x1, y1, x2, y2)
    coords_norm: Tuple[float, float, float, float]  # Нормализованные (0..1)
    block_type: BlockType             # TEXT | TABLE | IMAGE
    source: BlockSource               # USER | AUTO
    shape_type: ShapeType             # RECTANGLE | POLYGON
    polygon_points: Optional[List[Tuple[int, int]]]  # Вершины полигона
    image_file: Optional[str]         # Путь к кропу
    ocr_text: Optional[str]           # Результат OCR
    prompt: Optional[dict]            # {"system": "...", "user": "..."}
    hint: Optional[str]               # Подсказка для IMAGE блока
    pdfplumber_text: Optional[str]    # Сырой текст из PyMuPDF
```

#### BlockType

```python
class BlockType(Enum):
    TEXT = "text"      # Текстовый блок
    TABLE = "table"    # Таблица
    IMAGE = "image"    # Изображение/схема
```

#### Page / Document

Legacy-классы для обратной совместимости с GUI:

```python
@dataclass
class Page:
    page_number: int
    width: int
    height: int
    blocks: List[Block]

@dataclass
class Document:
    pdf_path: str
    pages: List[Page]
```

### Сериализация

```python
# Block → dict
block.to_dict()

# dict → Block  
Block.from_dict(data)

# Document → JSON file
AnnotationIO.save_annotation(document, "annotation.json")
AnnotationIO.load_annotation("annotation.json")
```

---

## Desktop-клиент (GUI)

### Структура модулей

```
app/gui/
├── main_window.py          # MainWindow (композиция миксинов)
├── menu_setup.py           # MenuSetupMixin - меню
├── panels_setup.py         # PanelsSetupMixin - панели
├── file_operations.py      # FileOperationsMixin - открытие/сохранение
├── block_handlers.py       # BlockHandlersMixin - работа с блоками
│
├── page_viewer.py          # PageViewer (QGraphicsView)
├── page_viewer_blocks.py   # BlockRenderingMixin
├── page_viewer_mouse.py    # MouseEventsMixin
├── page_viewer_polygon.py  # PolygonMixin
├── page_viewer_resize.py   # ResizeHandlesMixin
│
├── blocks_tree_manager.py  # Дерево блоков текущей страницы
├── navigation_manager.py   # Навигация + зум
├── prompt_manager.py       # Загрузка промптов из R2
│
├── remote_ocr/             # Панель Remote OCR
│   ├── panel.py            # RemoteOCRPanel - основной UI
│   ├── job_operations.py   # Операции с задачами
│   ├── download_mixin.py   # Скачивание результатов
│   ├── polling_controller.py # Polling статуса задач
│   ├── result_handler.py   # Обработка результатов
│   ├── table_manager.py    # Управление таблицей задач
│   └── signals.py          # Qt сигналы
│
├── project_tree/           # Дерево проектов (Supabase)
│   ├── widget.py           # ProjectTreeWidget
│   ├── tree_item_builder.py # Создание элементов
│   ├── annotation_operations.py # Операции с аннотациями
│   ├── pdf_status_manager.py # Статусы PDF
│   └── r2_viewer_integration.py # Интеграция с R2
│
└── dialogs/                # Диалоговые окна
    └── create_node_dialog.py # Диалог создания узла
```

### MainWindow

Главное окно использует паттерн **Mixin** для разделения ответственности:

```python
class MainWindow(MenuSetupMixin, PanelsSetupMixin,
                 FileOperationsMixin, BlockHandlersMixin, QMainWindow):
    def __init__(self):
        # Данные
        self.pdf_document: Optional[PDFDocument] = None
        self.annotation_document: Optional[Document] = None
        self.current_page: int = 0

        # Менеджеры
        self.prompt_manager = PromptManager(self)
        self.blocks_tree_manager = BlocksTreeManager(self, self.blocks_tree)
        self.navigation_manager = NavigationManager(self)

        # Remote OCR
        self.remote_ocr_panel = RemoteOCRPanel(self)
```

### PageViewer

Виджет отображения PDF страницы на базе `QGraphicsView`:

```python
class PageViewer(ContextMenuMixin, MouseEventsMixin,
                 BlockRenderingMixin, PolygonMixin,
                 ResizeHandlesMixin, QGraphicsView):

    # Сигналы
    blockDrawn = Signal(int, int, int, int)     # Нарисован прямоугольник
    polygonDrawn = Signal(list)                  # Нарисован полигон
    block_selected = Signal(int)                 # Выбран блок
    blocks_selected = Signal(list)               # Множественный выбор
    blockMoved = Signal(int, int, int, int, int) # Перемещён блок
    blockDeleted = Signal(int)                   # Удалён блок

    def set_page_image(self, pil_image, page_number, reset_zoom=True):
        """Установить изображение страницы"""

    def set_blocks(self, blocks: List[Block]):
        """Отобразить блоки на странице"""
```

### RemoteOCRPanel

Dock-панель для управления OCR-задачами (`app/gui/remote_ocr/panel.py`):

```python
class RemoteOCRPanel(QDockWidget):
    # Компоненты через композицию:
    # - JobOperationsMixin (job_operations.py)
    # - DownloadMixin (download_mixin.py)
    # - PollingController (polling_controller.py)
    # - TableManager (table_manager.py)
    # - ResultHandler (result_handler.py)

    def _create_job(self):
        """Создать новую OCR-задачу"""

    def _start_polling(self):
        """Запустить polling статусов"""

    def _download_result(self, job_id):
        """Скачать результат OCR"""
```

### ProjectTreeWidget

Виджет дерева проектов с lazy loading (`app/gui/project_tree/widget.py`):

```python
class ProjectTreeWidget(QWidget):
    document_selected = Signal(str, str)  # node_id, r2_key
    file_uploaded = Signal(str)           # local_path

    # Вспомогательные модули:
    # - tree_item_builder.py - создание элементов дерева
    # - annotation_operations.py - работа с аннотациями
    # - pdf_status_manager.py - статусы PDF документов
    # - r2_viewer_integration.py - интеграция с R2 просмотрщиком

    def _on_item_expanded(self, item):
        """Lazy loading — загрузка дочерних при раскрытии"""
```

---

## Remote OCR Server

### Компоненты

```
services/remote_ocr/server/
├── main.py              # FastAPI приложение
├── settings.py          # Конфигурация из env
├── celery_app.py        # Конфигурация Celery
├── tasks.py             # Celery задача run_ocr_task
├── rate_limiter.py      # Rate limiting для Datalab API
├── worker_pdf.py        # Работа с PDF
│
├── routes/              # API endpoints
│   ├── jobs/            # CRUD для задач
│   │   ├── router.py
│   │   ├── create_handler.py
│   │   ├── read_handlers.py
│   │   └── update_handlers.py
│   ├── storage.py       # R2 операции
│   └── tree.py          # Tree API
│
├── storage/             # Supabase CRUD
│   ├── storage.py       # Основные операции
│   └── storage_*.py     # Специфичные модули
│
└── node_storage/        # Хранение файлов узлов
    ├── repository.py
    └── file_manager.py
```

### Жизненный цикл задачи

```
         ┌────────┐
         │ draft  │ ← POST /jobs/draft (сохранение без OCR)
         └───┬────┘
             │ POST /jobs/{id}/start
             ▼
         ┌────────┐
    ┌────│ queued │◄──────────────────────────┐
    │    └───┬────┘                           │
    │        │ Celery: run_ocr_task           │
    │        ▼                                │
    │    ┌───────────┐    POST /jobs/{id}/    │
    │    │processing │────► pause ──► paused ─┤
    │    └─────┬─────┘                resume  │
    │          │                              │
    │          ├── success ──► done           │
    │          │                              │
    │          └── failure ──► error ─────────┘
    │                         restart
    │
    └── DELETE /jobs/{id}
```

### Статусы задач

| Status | Описание |
|--------|----------|
| `draft` | Черновик: PDF + разметка сохранены, OCR не запущен |
| `queued` | В очереди на обработку |
| `processing` | Обрабатывается воркером |
| `done` | Завершена успешно |
| `error` | Ошибка при обработке |
| `paused` | Приостановлена пользователем |

### Celery Worker

```python
@celery_app.task(bind=True, name="run_ocr_task", max_retries=3)
def run_ocr_task(self, job_id: str) -> dict:
    # 1. Скачать PDF и blocks.json из R2
    pdf_path, blocks_path = _download_job_files(job, work_dir)

    # 2. Вырезать кропы блоков
    strip_paths, strip_images, strips, image_blocks, _ = \
        crop_and_merge_blocks_from_pdf(pdf_path, blocks, crops_dir)

    # 3. OCR для TEXT/TABLE (объединённые полосы)
    for strip in strips:
        result = strip_backend.recognize(merged_image, prompt=prompt_data)

    # 4. OCR для IMAGE блоков (индивидуально)
    for block, crop, part_idx, total_parts in image_blocks:
        text = image_backend.recognize(crop, prompt=prompt_data)

    # 5. Генерация результатов
    generate_structured_markdown(pages, "result.md")

    # 6. Создание ZIP и загрузка в R2
    _upload_results_to_r2(job, work_dir)
```

---

## Tree Projects (Supabase)

### Иерархия узлов

```
PROJECT (Проект)
└── STAGE (Стадия: ПД / РД)
    └── SECTION (Раздел: АР, КР, ОВ...)
        └── TASK_FOLDER (Папка заданий)
            └── DOCUMENT (Документ PDF)
```

### TreeClient

```python
@dataclass
class TreeClient:
    supabase_url: str
    supabase_key: str
    client_id: str

    def get_root_nodes(self) -> List[TreeNode]:
        """Корневые проекты (parent_id IS NULL)"""

    def get_children(self, parent_id: str) -> List[TreeNode]:
        """Дочерние узлы (lazy loading)"""

    def create_node(self, node_type, name, parent_id=None, code=None):
        """Создать новый узел"""

    def add_document(self, parent_id, name, r2_key, file_size):
        """Добавить документ с автоверсионированием"""
```

### TreeNode

```python
@dataclass
class TreeNode:
    id: str
    parent_id: Optional[str]
    client_id: str
    node_type: NodeType      # project|stage|section|task_folder|document
    name: str
    code: Optional[str]      # Шифр (AR-01)
    version: int             # Версия документа
    status: NodeStatus       # active|completed|archived
    attributes: Dict         # r2_key, local_path, file_size...
    sort_order: int
    children: List[TreeNode]
```

### Справочники

**stage_types** — типы стадий:
- ПД: Проектная документация
- РД: Рабочая документация

**section_types** — типы разделов:
- АР: Архитектурные решения
- КР: Конструктивные решения
- ОВ: Отопление и вентиляция
- ВК: Водоснабжение и канализация
- ЭО: Электрооборудование
- СС: Слаботочные системы
- ГП: Генеральный план
- ПОС: Проект организации строительства
- ПЗ: Пояснительная записка

---

## Хранилище R2

### R2Storage

S3-совместимый клиент для Cloudflare R2:

```python
class R2Storage:
    def __init__(self):
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto"
        )

    def upload_file(self, local_path, remote_key) -> bool
    def download_file(self, remote_key, local_path) -> bool
    def upload_text(self, content, remote_key) -> bool
    def download_text(self, remote_key) -> Optional[str]
    def generate_presigned_url(self, remote_key, expiration=3600) -> str
    def delete_object(self, remote_key) -> bool
```

### Структура bucket

```
rd1/
├── prompts/
│   ├── text.json        # Промпт для TEXT блоков
│   ├── table.json       # Промпт для TABLE блоков
│   └── image.json       # Промпт для IMAGE блоков
│
├── ocr_jobs/
│   └── {job_id}/
│       ├── document.pdf
│       ├── blocks.json
│       ├── annotation.json
│       ├── result.md
│       ├── result.zip
│       └── crops/
│           ├── image_{block_id}.pdf
│           └── ...
│
└── ocr_results/
    └── {project_name}/
        └── ...
```

---

## OCR движки

### Интерфейс OCRBackend

```python
class OCRBackend(Protocol):
    def recognize(self, image: Image.Image,
                  prompt: Optional[dict] = None,
                  json_mode: bool = None) -> str:
        """Распознать текст на изображении"""
```

### OpenRouterBackend

Использует OpenRouter API для доступа к VLM-моделям:

```python
class OpenRouterBackend:
    DEFAULT_MODEL = "qwen/qwen3-vl-30b-a3b-instruct"

    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name

    def recognize(self, image, prompt=None, json_mode=None) -> str:
        # 1. Конвертация изображения в base64
        # 2. Построение payload с system/user messages
        # 3. POST запрос к openrouter.ai/api/v1/chat/completions
        # 4. Парсинг ответа
```

Особенности:
- Автоматический выбор дешевейшего провайдера
- Поддержка Gemini 3 (отправка PDF вместо PNG)
- Auto-detect JSON mode по тексту промпта

### DatalabOCRBackend

Использует Datalab Marker API для сегментации и OCR:

```python
class DatalabOCRBackend:
    def recognize(self, image, prompt=None, json_mode=None) -> str:
        # 1. Конвертация в PDF
        # 2. POST к api.datalab.to/api/v1/marker
        # 3. Polling до готовности
        # 4. Получение Markdown результата
```

### Фабрика create_ocr_engine

```python
def create_ocr_engine(backend: str = "dummy", **kwargs) -> OCRBackend:
    if backend == "openrouter":
        return OpenRouterBackend(**kwargs)
    elif backend == "datalab":
        return DatalabOCRBackend(**kwargs)
    else:
        return DummyOCRBackend()
```

---

## API Reference

### Health Check

```
GET /health

Response: {"ok": true}
```

### Jobs

#### Создать задачу

```
POST /jobs
Content-Type: multipart/form-data

Form fields:
  - client_id: str
  - document_id: str (SHA256 хеш PDF)
  - document_name: str
  - task_name: str
  - engine: str (openrouter|datalab)
  - text_model: str
  - table_model: str
  - image_model: str

Files:
  - pdf: application/pdf
  - blocks_file: application/json

Response:
{
  "id": "uuid",
  "status": "queued",
  "progress": 0,
  "document_id": "sha256",
  "document_name": "file.pdf",
  "task_name": "My Task"
}
```

#### Создать черновик

```
POST /jobs/draft
Content-Type: multipart/form-data

Form fields:
  - client_id: str
  - document_id: str
  - document_name: str
  - task_name: str
  - annotation_json: str (JSON Document)

Files:
  - pdf: application/pdf

Response: JobInfo (status="draft")
```

#### Запустить черновик

```
POST /jobs/{job_id}/start
Form fields:
  - engine: str
  - text_model: str
  - table_model: str
  - image_model: str

Response: {"ok": true, "status": "queued"}
```

#### Список задач

```
GET /jobs
Query params:
  - client_id: str (опционально)
  - document_id: str (опционально)

Response: [JobInfo, ...]
```

#### Получить задачу

```
GET /jobs/{job_id}

Response: JobInfo
```

#### Детали задачи

```
GET /jobs/{job_id}/details

Response:
{
  ...JobInfo,
  "block_stats": {"total": 10, "text": 5, "table": 3, "image": 2},
  "job_settings": {"text_model": "...", "table_model": "..."},
  "r2_base_url": "https://pub-xxx.r2.dev/ocr_jobs/uuid",
  "r2_files": [{"name": "result.md", "path": "result.md", "icon": "📄"}]
}
```

#### Скачать результат

```
GET /jobs/{job_id}/result

Response: {"download_url": "presigned_url", "file_name": "result.zip"}
```

#### Управление

```
POST /jobs/{job_id}/pause    → {"ok": true, "status": "paused"}
POST /jobs/{job_id}/resume   → {"ok": true, "status": "queued"}
POST /jobs/{job_id}/restart  → {"ok": true, "status": "queued"}
PATCH /jobs/{job_id}         → Form: task_name → {"ok": true}
DELETE /jobs/{job_id}        → {"ok": true, "deleted_job_id": "..."}
```

---

## База данных

### Схема Supabase

#### jobs

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | ID задачи |
| client_id | text | ID клиента |
| document_id | text | SHA256 хеш PDF |
| document_name | text | Имя файла |
| task_name | text | Название задачи |
| status | text | draft\|queued\|processing\|done\|error\|paused |
| progress | real | Прогресс 0..1 |
| engine | text | openrouter\|datalab |
| r2_prefix | text | Префикс в R2 |
| error_message | text | Сообщение об ошибке |
| created_at | timestamptz | |
| updated_at | timestamptz | |

#### job_files

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| job_id | uuid FK | → jobs.id |
| file_type | text | pdf\|blocks\|annotation\|result_md\|result_zip\|crop |
| r2_key | text | Ключ в R2 |
| file_name | text | Имя файла |
| file_size | bigint | Размер в байтах |
| created_at | timestamptz | |

#### job_settings

| Column | Type | Description |
|--------|------|-------------|
| job_id | uuid PK FK | → jobs.id |
| text_model | text | Модель для TEXT |
| table_model | text | Модель для TABLE |
| image_model | text | Модель для IMAGE |

#### tree_nodes

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| parent_id | uuid FK | → tree_nodes.id (CASCADE) |
| client_id | text | ID клиента |
| node_type | text | project\|stage\|section\|task_folder\|document |
| name | text | Название |
| code | text | Шифр (AR-01) |
| version | integer | Версия |
| status | text | active\|completed\|archived |
| attributes | jsonb | {r2_key, local_path, file_size, ...} |
| sort_order | integer | Порядок сортировки |

#### tree_documents

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| node_id | uuid FK | → tree_nodes.id |
| file_name | text | |
| r2_key | text | |
| file_size | bigint | |
| mime_type | text | |
| version | integer | |

#### stage_types / section_types

Справочники типов стадий и разделов.

---

## Развёртывание

### Environment Variables

```env
# Remote OCR сервер
REMOTE_OCR_BASE_URL=http://localhost:8000
REMOTE_OCR_API_KEY=optional_api_key

# Supabase
SUPABASE_URL=https://project.supabase.co
SUPABASE_KEY=your_anon_key

# R2 Storage
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=rd1
R2_PUBLIC_URL=https://pub-xxxxx.r2.dev

# OCR API Keys
OPENROUTER_API_KEY=sk-or-...
DATALAB_API_KEY=...

# Redis (для Celery)
REDIS_URL=redis://redis:6379/0

# Лимиты
MAX_CONCURRENT_JOBS=2
DATALAB_MAX_RPM=180
DATALAB_MAX_CONCURRENT=5
```

### Docker Compose (Development)

```yaml
# docker-compose.remote-ocr.dev.yml
services:
  api:
    build: ./services/remote_ocr
    ports: ["8000:8000"]
    environment:
      - SUPABASE_URL
      - SUPABASE_KEY
      - OPENROUTER_API_KEY
      - REDIS_URL=redis://redis:6379/0
    depends_on: [redis]

  worker:
    build: ./services/remote_ocr
    command: celery -A server.celery_app worker -l info
    environment: ...
    depends_on: [redis, api]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

### Запуск

```bash
# Desktop клиент
python app/main.py

# Remote OCR сервер (Docker)
docker compose -f docker-compose.remote-ocr.dev.yml up --build

# Remote OCR сервер (без Docker)
cd services/remote_ocr
uvicorn server.main:app --host 0.0.0.0 --port 8000

# Celery worker (без Docker)
celery -A server.celery_app worker -l info
```

### Сборка EXE

```bash
python build.py
# Результат: dist/PDFAnnotation.exe
```

---

## Дополнительные модули

### rd_core/pdf_utils.py

Работа с PDF через PyMuPDF:

```python
PDF_RENDER_DPI = 300
PDF_RENDER_ZOOM = 300 / 72  # ≈ 4.167

def open_pdf(path: str) -> fitz.Document
def render_page_to_image(doc, page_index, zoom) -> Image.Image
def extract_text_pdfplumber(pdf_path, page_index, bbox) -> str
def get_pdf_page_size(pdf_path, page_index) -> Tuple[float, float]

class PDFDocument:
    """Обёртка с context manager"""
    def open(self) -> bool
    def close(self)
    def render_page(self, page_number, zoom) -> Optional[Image.Image]
    def get_page_dimensions(self, page_number, zoom) -> Optional[Tuple]
```

### rd_core/annotation_io.py

Сохранение/загрузка разметки:

```python
class AnnotationIO:
    @staticmethod
    def save_annotation(document: Document, file_path: str)

    @staticmethod
    def load_annotation(file_path: str) -> Optional[Document]
```

---

## Логирование

Конфигурация в `app/main.py`:

```python
setup_logging(log_level=logging.INFO)
# Файл: logs/app.log
# Формат: 2025-01-01 12:00:00 - module - LEVEL - message
```

Подавление шума от библиотек:
- PIL, boto3, botocore, httpx, urllib3 → WARNING

---

## Лицензия и автор

**PDF Annotation Tool**  
Python 3.11 | PySide6 | PyMuPDF | Cloudflare R2 | Supabase
