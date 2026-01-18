# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Core Structure** - Desktop PDF annotation tool with distributed OCR processing.

Stack: PySide6 (Qt 6), FastAPI, Celery + Redis, Supabase (PostgreSQL), Cloudflare R2.

Python 3.11+ required.

## Commands

### Setup
```bash
pip install -r requirements.txt
```

### Desktop Client
```bash
python apps/rd_desktop/main.py         # Run application
python build.py                        # Build executable → dist/CoreStructure.exe
```

### Tests
```bash
pytest                                # Run all tests
pytest tests/test_crop_determinism.py  # Run single test file
pytest -v                             # Verbose output
```

### Remote OCR Server

#### Quick Start (Windows PowerShell)

```powershell
.\start-server.ps1           # Production (all workers)
.\start-server.ps1 -Dev      # Development (universal worker)
.\start-server.ps1 -Build    # Rebuild images before start
.\stop-server.ps1            # Stop all containers
```

#### Docker Compose (Production)
```bash
cp env.example .env              # Configure environment variables
docker compose up -d --build     # Start server (listens on 127.0.0.1:18000)
```

#### Development
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

**RAM requirements:**
- Production: ~12GB (5 specialized workers с лимитами)
- Development: без лимитов (1 universal worker)

**Desktop client connection:** Set `REMOTE_OCR_BASE_URL=http://localhost:18000` in `.env`

#### Manual (without Docker)
```bash
redis-server                                                              # Terminal 1
uvicorn apps.remote_ocr_server.main:app --host 0.0.0.0 --port 8000 --reload  # Terminal 2
celery -A apps.remote_ocr_server.celery_app worker --loglevel=info --concurrency=1  # Terminal 3
```

### Health Checks
```bash
curl http://localhost:18000/health   # Production (default port)
curl http://localhost:18000/queue
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

### Key Components (Clean/Hexagonal Architecture)

| Directory | Layer | Purpose |
|-----------|-------|---------|
| `packages/rd_domain/` | 0 - Domain | Domain models, ArmorID, annotation I/O (no dependencies) |
| `packages/rd_pipeline/` | 1 - Business | OCR backends, PDF utils, output generators, processing |
| `packages/rd_adapters/` | 2 - Infrastructure | R2 storage adapters, caching |
| `apps/rd_desktop/` | Application | Desktop GUI (PySide6). Entry: `apps/rd_desktop/main.py` |
| `apps/remote_ocr_server/` | Application | FastAPI server + Celery tasks |
| `database/migrations/` | - | SQL migration files |

### Architectural Patterns

**Mixin Pattern (GUI)**: `MainWindow` composes multiple mixins - each handles specific responsibility (menus, file ops, block handlers).

**Protocol Pattern (OCR)**: `OCRBackend` protocol in `rd_pipeline/ocr/ports.py`. Implementations: `OpenRouterBackend`, `DatalabOCRBackend`. Factory: `create_ocr_engine()`.

**Context Manager (PDF)**: `PDFDocument` in `rd_pipeline/pdf/utils.py` uses `__enter__`/`__exit__` for resource cleanup.

**ArmorID (Block IDs)**: OCR-resistant ID format `XXXX-XXXX-XXX` using 26-character alphabet. See `rd_domain/ids/armor_id.py`. Use `generate_armor_id()` for new blocks.

**Offline Mode**: App queues operations when disconnected. `ConnectionManager` monitors connectivity, `SyncQueue` stores pending operations. Auto-syncs on reconnection.

### Data Models (`rd_domain/models/`)

```python
Block      # Annotation unit: id, page_index, coords_px, coords_norm, block_type, shape_type, polygon_points, ocr_text
Document   # Collection of pages
Page       # Page with blocks list
```

Block types: `TEXT`, `IMAGE`. Shape types: `RECTANGLE`, `POLYGON`. Block source: `MANUAL`, `OCR`.

### Database Tables (Supabase)

- `jobs` - OCR task records (status: draft/queued/processing/done/error)
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

**Add GUI feature**: Create mixin in `apps/rd_desktop/gui/`, add to MainWindow inheritance.

**Add OCR engine**: Implement `OCRBackend` protocol in `rd_pipeline/ocr/backends/`, register in `factory.py`.

**Add API endpoint**: Create route in `apps/remote_ocr_server/routes/`, include in `main.py`.

**Modify database**: Add migration in `database/migrations/`, document in `docs/DATABASE.md`.

## Configuration

Copy `env.example` to `.env` and configure:

Required `.env` variables:
- `SUPABASE_URL`, `SUPABASE_KEY` - Database
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` - Storage
- `OPENROUTER_API_KEY` and/or `DATALAB_API_KEY` - OCR engines
- `REMOTE_OCR_BASE_URL` - Server URL (default: http://localhost:18000)
- `REDIS_URL` - For server (default: redis://redis:6379/0)

Docker-specific (optional):
- `REMOTE_OCR_BIND_ADDR` - Bind address (default: 127.0.0.1)
- `REMOTE_OCR_PORT` - External port (default: 18000)

## Code Style

From `.cursorrules`: Be maximally concise. Code only in code blocks. Changes as minimal diff. No explanations unless asked. If text needed - max 5 points, each ≤ 12 words.

**Git workflow**: После внесения изменений в код ВСЕГДА делай коммит и пуш. Сообщения коммитов пиши на русском языке.

## Language

Все планы, ответы и объяснения генерируй на русском языке.
