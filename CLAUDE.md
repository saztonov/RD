# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Core Structure** - Desktop PDF annotation tool with distributed OCR processing.

Stack: PySide6 (Qt 6), FastAPI, Celery + Redis, Supabase (PostgreSQL), Cloudflare R2.

## Language / Язык

**Все планы и описания задач выводить на русском языке.**

## Commands

### Desktop Client
```bash
python app/main.py                    # Run application
python build.py                        # Build executable → dist/CoreStructure.exe
```

### Remote OCR Server
```bash
# Docker (recommended)
docker compose up --build

# Manual
redis-server                                                              # Terminal 1
uvicorn services.remote_ocr.server.main:app --host 0.0.0.0 --port 8000 --reload  # Terminal 2
celery -A services.remote_ocr.server.celery_app worker --loglevel=info --concurrency=1  # Terminal 3
```

### Health Checks
```bash
curl http://localhost:8000/health
curl http://localhost:8000/queue
```

## Architecture

```
Desktop Client (PySide6)
    ├─→ RemoteOCRClient (HTTP) ──→ Remote OCR Server (FastAPI)
    │                                 ├─→ Celery Workers (Redis)
    │                                 ├─→ Supabase (jobs, tree_nodes)
    │                                 └─→ R2 Storage (files)
    ├─→ TreeClient (REST) ──→ Supabase (project hierarchy)
    └─→ R2Storage (boto3) ──→ Cloudflare R2 (prompts, results)
```

### Key Components

| Directory | Purpose |
|-----------|---------|
| `app/` | Desktop GUI (PySide6). Entry: `app/main.py` |
| `app/gui/` | GUI modules (~80). Core: `main_window.py`, `page_viewer.py` |
| `rd_core/` | Core logic: models, PDF utils, R2 storage, OCR engines |
| `rd_core/ocr/` | OCR backends (OpenRouter, Datalab). Protocol: `base.py` |
| `services/remote_ocr/server/` | FastAPI server + Celery tasks |
| `database/migrations/` | SQL migration files |
| `docs/` | Full documentation |

### Architectural Patterns

**Mixin Pattern (GUI)**: `MainWindow` composes multiple mixins - each handles specific responsibility (menus, file ops, block handlers).

**Protocol Pattern (OCR)**: `OCRBackend` protocol in `rd_core/ocr/base.py`. Implementations: `OpenRouterBackend`, `DatalabOCRBackend`. Factory: `create_ocr_engine()`.

**Context Manager (PDF)**: `PDFDocument` in `rd_core/pdf_utils.py` uses `__enter__`/`__exit__` for resource cleanup.

### Data Models (`rd_core/models/`)

```python
Block      # block.py - annotation with coords, groups, categories
ArmorID    # armor_id.py - OCR-resistant ID format (XXXX-XXXX-XXX)
Document   # document.py - collection of pages
Page       # document.py - page with blocks list
BlockType  # enums.py - TEXT, IMAGE
ShapeType  # enums.py - RECTANGLE, POLYGON
```

### Database Tables (Supabase v2)

- `jobs` - OCR tasks (status: draft/queued/processing/done/error/paused)
- `job_files` - Job files (pdf, blocks, results, crops)
- `job_settings` - Model settings per job
- `tree_nodes` - Project hierarchy v2 (path, depth, pdf_status, is_locked)
- `node_files` - Node files (PDF, annotations, OCR results, crops)

node_type v2: `folder` | `document` (legacy types in attributes.legacy_node_type)

### Server Components v2

| Module | Purpose |
|--------|---------|
| `task_ocr_twopass.py` | Two-pass OCR (memory-efficient) |
| `pdf_streaming_twopass.py` | Streaming PDF for large files |
| `async_r2_storage.py` | Async R2 operations |
| `block_verification.py` | Block coordinate verification |
| `debounced_updater.py` | Debounce status updates to Supabase |
| `block_id_matcher.py` | Match OCR results to blocks |

### Client Caching & Sync

| Module | Purpose |
|--------|---------|
| `annotation_cache.py` | Annotation cache with R2 sync |
| `sync_queue.py` | Offline sync queue |
| `tree_cache_ops.py` | Tree operations caching |

### OCR Job Lifecycle (Two-Pass)

1. User selects blocks → `RemoteOCRClient.create_job()` → POST /jobs
2. Server: PDF + blocks.json → R2, job → Supabase (status=queued)
3. Celery worker two-pass:
   - PASS 1: Stream PDF → crops to disk (memory-efficient)
   - PASS 2: OCR from manifest → merge results
4. Upload results → status=done
5. Client polls GET /jobs/{id} → downloads result

## Extension Points

**Add GUI feature**: Create mixin in `app/gui/`, add to MainWindow inheritance.

**Add OCR engine**: Implement `OCRBackend` protocol, add to `rd_core/ocr/`, register in `factory.py`.

**Add API endpoint**: Create route in `services/remote_ocr/server/routes/`, include in `main.py`.

**Modify database**: Add migration in `database/migrations/`, document in `docs/DATABASE.md`.

## Configuration

Required `.env` variables:
- `SUPABASE_URL`, `SUPABASE_KEY` - Database
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` - Storage
- `OPENROUTER_API_KEY` and/or `DATALAB_API_KEY` - OCR engines
- `REMOTE_OCR_BASE_URL` - Server URL (default: http://localhost:8000)
- `REDIS_URL` - For server (default: redis://redis:6379/0)

## Logging (Server)

Централизованная система логирования в `services/remote_ocr/server/`.

### Конфигурация

| Переменная | Значения | По умолчанию |
|------------|----------|--------------|
| `LOG_LEVEL` | DEBUG, INFO, WARNING, ERROR | INFO |
| `LOG_FORMAT` | json, text | json |

### Ключевые модули

| Модуль | Назначение |
|--------|------------|
| `logging_config.py` | JSONFormatter, setup_logging(), get_logger() |
| `celery_signals.py` | Celery lifecycle (task_prerun/postrun/failure) |

### Использование

```python
from .logging_config import get_logger

logger = get_logger(__name__)
logger.info("Message", extra={"job_id": "abc-123", "event": "task_started"})
```

### JSON формат (production)

```json
{"timestamp": "2026-01-25T12:34:56Z", "level": "INFO", "logger": "tasks", "message": "Task completed", "job_id": "abc-123", "duration_ms": 45230}
```

### Extra поля

Поддерживаемые поля для `extra={}`: `job_id`, `task_id`, `block_id`, `strip_id`, `page_index`, `duration_ms`, `memory_mb`, `event`, `status`, `status_code`, `method`, `path`, `exception_type`.

## Code Style

From `.cursorrules`: Be maximally concise. Code only in code blocks. Changes as minimal diff. No explanations unless asked. If text needed - max 5 points, each ≤ 12 words.

## Documentation

- `docs/ARCHITECTURE.md` - Full technical documentation
- `docs/DEVELOPER_GUIDE.md` - Code examples and patterns
- `docs/DATABASE.md` - Complete DB schema
- `docs/REMOTE_OCR_SERVER.md` - Server API reference
