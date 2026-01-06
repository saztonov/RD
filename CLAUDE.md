# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Core Structure** - Desktop PDF annotation tool with distributed OCR processing.

Stack: PySide6 (Qt 6), FastAPI, Celery + Redis, Supabase (PostgreSQL), Cloudflare R2.

## Commands

### Desktop Client
```bash
python app/main.py                    # Run application
python build.py                        # Build executable → dist/CoreStructure.exe
```

### Remote OCR Server
```bash
# Docker (recommended)
docker compose -f docker-compose.remote-ocr.dev.yml up --build

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
| `app/gui/` | 57 GUI modules. Core: `main_window.py`, `page_viewer.py` |
| `rd_core/` | Core logic: models, PDF utils, R2 storage, OCR engines |
| `rd_core/ocr/` | OCR backends (OpenRouter, Datalab). Protocol: `base.py` |
| `services/remote_ocr/server/` | FastAPI server + Celery tasks |
| `database/migrations/` | SQL migration files |
| `docs/` | Full documentation |

### Architectural Patterns

**Mixin Pattern (GUI)**: `MainWindow` composes multiple mixins - each handles specific responsibility (menus, file ops, block handlers).

**Protocol Pattern (OCR)**: `OCRBackend` protocol in `rd_core/ocr/base.py`. Implementations: `OpenRouterBackend`, `DatalabOCRBackend`. Factory: `create_ocr_engine()`.

**Context Manager (PDF)**: `PDFDocument` in `rd_core/pdf_utils.py` uses `__enter__`/`__exit__` for resource cleanup.

### Data Models (`rd_core/models.py`)

```python
Block      # Annotation unit: id, page_index, coords_px, coords_norm, block_type, shape_type, polygon_points, ocr_text
Document   # Collection of pages
Page       # Page with blocks list
```

Block types: `TEXT`, `TABLE`, `IMAGE`. Shape types: `RECTANGLE`, `POLYGON`.

### Database Tables (Supabase)

- `jobs` - OCR task records (status: draft/queued/processing/done/error/paused)
- `job_files` - File references (pdf, blocks, results, crops)
- `job_settings` - Model selections per job
- `tree_nodes` - Hierarchical project structure
- `tree_documents` - Document versioning

### OCR Job Lifecycle

1. User selects blocks → `RemoteOCRClient.create_job()` → POST /jobs
2. Server stores PDF + blocks.json → R2, creates job → Supabase (status=queued)
3. Celery worker: download → crop → OCR → merge → upload results → status=done
4. Client polls GET /jobs/{id} → downloads result

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

## Code Style

From `.cursorrules`: Be maximally concise. Code only in code blocks. Changes as minimal diff. No explanations unless asked. If text needed - max 5 points, each ≤ 12 words.

## Documentation

- `docs/ARCHITECTURE.md` - Full technical documentation
- `docs/DEVELOPER_GUIDE.md` - Code examples and patterns
- `docs/DATABASE.md` - Complete DB schema
- `docs/REMOTE_OCR_SERVER.md` - Server API reference
