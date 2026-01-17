# Project Invariants

This document defines architectural invariants that must be maintained across the codebase.
Useful for both human developers and AI assistants (Claude Code, etc.).

## Block Coordinates

- **Canon**: `coords_norm` (0.0-1.0) - normalized coordinates relative to page dimensions
- **Derived**: `coords_px` = `coords_norm * page_dimensions`
- On DPI/render change: recalculate `coords_px` from `coords_norm`
- `polygon_points` (if present) are also stored as pixel values and must be scaled proportionally

```python
# Conversion example
coords_px = Block.norm_to_px(coords_norm, page_width, page_height)
coords_norm = Block.px_to_norm(coords_px, page_width, page_height)
```

## R2 Storage Keys

| Context | Key Pattern |
|---------|-------------|
| With node_id | `tree_docs/{node_id}/ocr_runs/{job_id}/` |
| Without node_id | `ocr_jobs/{job_id}/` |
| PDF (always) | `{prefix}/document.pdf` |
| Blocks | `{prefix}/blocks.json` or `{prefix}/annotation.json` |
| Results | `{prefix}/result.json` |
| Crops | `{prefix}/crops/{block_id}.png` |

## Job Statuses

```
draft → queued → processing → done
                          ↘
                         error

pending_upload → queued  (v2 direct upload flow)
```

- `draft` - created but not queued
- `queued` - waiting for worker
- `processing` - worker is processing
- `done` - completed successfully
- `error` - terminal error state
- `pending_upload` - waiting for direct R2 upload (v2 API: /jobs/init → /jobs/{id}/confirm)

## Architecture Layers

```
Layer 0 - Domain (rd_domain)
├── Models: Block, Document, Page
├── ArmorID generation
├── Annotation I/O
└── NO external dependencies

Layer 1 - Business Logic (rd_pipeline)
├── OCR backends and protocols
├── PDF utilities
├── Output generators
├── Processing algorithms
└── Depends on: rd_domain only

Layer 2 - Infrastructure (rd_adapters)
├── R2 storage adapters
├── Caching
├── Error handling
└── Depends on: rd_domain

Layer 3 - Applications (apps/)
├── rd_desktop - Desktop GUI
├── remote_ocr_server - FastAPI + Celery
└── Depends on: all packages
```

## Import Rules

| From | Can Import |
|------|-----------|
| `rd_domain` | stdlib only |
| `rd_pipeline` | `rd_domain` |
| `rd_adapters` | `rd_domain` |
| `apps/*` | all packages |

**Forbidden:**
- `rd_domain` importing from `rd_pipeline` or `rd_adapters`
- `packages/*` importing from `apps/*`
- Circular imports between packages

## Security Invariants

| Component | Allowed Credentials |
|-----------|-------------------|
| Desktop client | Supabase `anon` JWT, R2 read credentials |
| Remote OCR server | Supabase `service_role`, OCR API keys, R2 full access |

**Never in desktop code:**
- `service_role` Supabase key
- OpenRouter/Datalab API keys
- R2 write credentials (use presigned URLs)

## Adapter Rules

- Single source of truth: `packages/rd_adapters/storage/`
- NO duplicate storage implementations in `apps/`
- Server and desktop must use the same adapter classes
- Configuration via `R2Config` dataclass or environment variables

## OCR Backend Protocol

All OCR backends must implement:

```python
class OCRBackend(Protocol):
    def recognize(self, image: Image, prompt: str) -> str: ...
```

Backends are created via factory: `create_ocr_engine(engine_type, **kwargs)`

Available types: `openrouter`, `datalab`, `dummy`

## Block Types and Categories

| BlockType | Processing | Preprocess Mode |
|-----------|-----------|-----------------|
| `TEXT` | Strip grouping, text OCR | Grayscale + high contrast + sharpen |
| `IMAGE` | Individual crop, image description | Minimal (preserve colors) |
| `STAMP` | Individual crop, stamp recognition | Grayscale + median filter (denoise) |

Category codes (for IMAGE blocks): `stamp`, `photo`, `diagram`, `chart`, etc.

### Image Preprocessing

Preprocessing is applied before OCR to improve recognition quality:

```python
from rd_pipeline.processing import PreprocessMode, preprocess_crop, get_preprocess_mode_for_block

# Auto-detect mode from block type
mode = get_preprocess_mode_for_block(block)

# Apply preprocessing
processed_image = preprocess_crop(image, mode)
```

| Mode | Grayscale | Contrast | Sharpen | Denoise |
|------|-----------|----------|---------|---------|
| `TEXT` | Yes | High (1.5) | Yes | No |
| `IMAGE` | No | No | No | No |
| `STAMP` | Yes | No | No | MedianFilter(3) |

## Validation Limits

| Resource | Limit | Enforced In |
|----------|-------|-------------|
| PDF size | 500 MB | `validation.py` |
| PDF magic bytes | `%PDF` header | `validation.py` |
| Blocks count | 10,000 | `validation.py` |
| Blocks JSON size | 50 MB | `validation.py` |
| Job queue | configurable (default 100) | `queue_checker.py` |

### Input Validation

All uploads are validated before processing:

```python
from apps.remote_ocr_server.validation import validate_pdf_upload, validate_blocks_json

# In route handler:
await validate_pdf_upload(pdf_file)  # Raises HTTPException 400 on failure
blocks_data = validate_blocks_json(blocks_json)  # Returns parsed dict or raises
```

Validation checks:
- PDF: magic bytes (`%PDF`), file size limit
- Blocks: valid JSON, block count limit, JSON size limit

## Job Status Updates

Desktop client supports two modes for receiving job status updates:

### Supabase Realtime (Primary)

Uses WebSocket connection to Supabase for instant updates:
- Connects to `wss://{project}.supabase.co/realtime/v1/websocket`
- Subscribes to `postgres_changes` on `jobs` table
- Receives INSERT/UPDATE/DELETE events in real-time
- Polling interval reduced to 2 minutes (sync only)

```python
from apps.rd_desktop.supabase_realtime import SupabaseRealtimeClient

client = SupabaseRealtimeClient()
client.job_changed.connect(on_job_update)
client.subscribe_to_jobs()
client.connect_to_realtime()
```

### HTTP Polling (Fallback)

Falls back to HTTP polling when Realtime is unavailable:
- `GET /jobs/changes?since={timestamp}` - incremental updates
- Adaptive intervals: 15s (active jobs), 60s (idle), exponential backoff on errors
- Automatic switch when Realtime disconnects

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Required for Realtime |
| `SUPABASE_KEY` | Required for Realtime (anon key) |
| `DISABLE_REALTIME` | Set to `1` to force polling mode |

## Testing Invariants

- Unit tests in `tests/`
- Run with `pytest`
- No network calls in unit tests (mock external services)
- Desktop app tests: mock R2, Supabase, OCR backends
