# CLAUDE.md

Руководство для Claude Code при работе с кодом этого репозитория.

## Оглавление

- [Обзор проекта](#обзор-проекта)
- [Команды](#команды)
- [Архитектура](#архитектура)
- [Точки расширения](#точки-расширения)
- [Конфигурация](#конфигурация)
- [Стиль кода](#стиль-кода)
- [Язык](#язык)

## Обзор проекта

**Core Structure** — десктоп-приложение для аннотирования PDF с распределённой OCR-обработкой.

Стек: PySide6 (Qt 6), FastAPI, Celery + Redis, Supabase (PostgreSQL), Cloudflare R2.

Python 3.11+ обязателен.

## Команды

### Установка
```bash
pip install -r requirements.txt
```

### Десктоп клиент
```bash
python apps/rd_desktop/main.py         # Запуск приложения
python build.py                        # Сборка → dist/CoreStructure.exe
```

### Тесты
```bash
pytest                                # Все тесты
pytest tests/test_crop_determinism.py  # Один файл
pytest -v                             # Подробный вывод
```

### Remote OCR Server

#### Быстрый старт (Windows PowerShell)

```powershell
.\start-server.ps1           # Production (все воркеры)
.\start-server.ps1 -Dev      # Development (один универсальный воркер)
.\start-server.ps1 -Build    # Пересборка образов
.\stop-server.ps1            # Остановка контейнеров
```

#### Docker Compose (Production)
```bash
cp env.example .env              # Настройка переменных окружения
docker compose up -d --build     # Запуск (порт 127.0.0.1:18000)
```

#### Development
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

**Требования к RAM:**
- Production: ~12GB (5 специализированных воркеров с лимитами)
- Development: без лимитов (1 универсальный воркер)

**Подключение клиента:** Установите `REMOTE_OCR_BASE_URL=http://localhost:18000` в `.env`

#### Без Docker
```bash
redis-server                                                              # Терминал 1
uvicorn apps.remote_ocr_server.main:app --host 0.0.0.0 --port 8000 --reload  # Терминал 2
celery -A apps.remote_ocr_server.celery_app worker --loglevel=info --concurrency=1  # Терминал 3
```

### Health Checks
```bash
curl http://localhost:18000/health   # Production (порт по умолчанию)
curl http://localhost:18000/queue
```

## Архитектура

```
Desktop Client (PySide6)
    ├─→ RemoteOCRClient (HTTP) ──→ Remote OCR Server (FastAPI)
    │                                 ├─→ Celery Workers (Redis)
    │                                 ├─→ Supabase (jobs, tree_nodes)
    │                                 └─→ R2 Storage (файлы)
    ├─→ TreeClient (REST) ──→ Supabase (иерархия проектов)
    └─→ R2Storage (boto3) ──→ Cloudflare R2 (промпты, результаты)
```

### Ключевые компоненты (Clean/Hexagonal Architecture)

| Директория | Слой | Назначение |
|------------|------|------------|
| `packages/rd_domain/` | 0 - Domain | Доменные модели, ArmorID, аннотации (без зависимостей) |
| `packages/rd_pipeline/` | 1 - Business | OCR backends, PDF утилиты, генераторы вывода |
| `packages/rd_adapters/` | 2 - Infrastructure | R2 storage адаптеры, кэширование |
| `apps/rd_desktop/` | Application | Desktop GUI (PySide6). Точка входа: `apps/rd_desktop/main.py` |
| `apps/remote_ocr_server/` | Application | FastAPI сервер + Celery задачи |
| `database/migrations/` | - | SQL миграции |

Подробная документация пакетов:
- [packages/rd_domain/README.md](packages/rd_domain/README.md)
- [packages/rd_pipeline/README.md](packages/rd_pipeline/README.md)
- [packages/rd_adapters/README.md](packages/rd_adapters/README.md)

### Архитектурные паттерны

**Mixin Pattern (GUI)**: `MainWindow` компонует несколько миксинов — каждый отвечает за свою область (меню, файловые операции, обработчики блоков).

**Protocol Pattern (OCR)**: Протокол `OCRBackend` в `rd_pipeline/ocr/ports.py`. Реализации: `OpenRouterBackend`, `DatalabOCRBackend`. Фабрика: `create_ocr_engine()`.

**Context Manager (PDF)**: `PDFDocument` в `rd_pipeline/pdf/utils.py` использует `__enter__`/`__exit__` для управления ресурсами.

**ArmorID (Block IDs)**: OCR-устойчивый формат ID `XXXX-XXXX-XXX` с 26-символьным алфавитом. См. `rd_domain/ids/armor_id.py`. Используйте `generate_armor_id()` для новых блоков.

**Offline Mode**: Приложение ставит операции в очередь при отключении. `ConnectionManager` мониторит соединение, `SyncQueue` хранит отложенные операции. Автосинхронизация при переподключении.

### Модели данных (`rd_domain/models/`)

```python
Block      # Единица аннотации: id, page_index, coords_px, coords_norm, block_type, shape_type, polygon_points, ocr_text
Document   # Коллекция страниц
Page       # Страница со списком блоков
```

Типы блоков: `TEXT`, `IMAGE`. Типы форм: `RECTANGLE`, `POLYGON`. Источник блока: `MANUAL`, `OCR`.

### Таблицы БД (Supabase)

- `jobs` — записи OCR задач (статус: draft/queued/processing/done/error)
- `job_files` — ссылки на файлы (pdf, blocks, results, crops)
- `job_settings` — выбор моделей для задачи
- `tree_nodes` — иерархия проектов
- `tree_documents` — версионирование документов

### Жизненный цикл OCR задачи

1. Пользователь выделяет блоки → `RemoteOCRClient.create_job()` → POST /jobs
2. Сервер сохраняет PDF + blocks.json → R2, создаёт job → Supabase (status=queued)
3. Celery worker: скачивание → crop → OCR → merge → загрузка результатов → status=done
4. Клиент опрашивает GET /jobs/{id} → скачивает результат

**API документация:** [docs/API.md](docs/API.md)

## Точки расширения

**Добавить GUI feature**: Создать mixin в `apps/rd_desktop/gui/`, добавить в наследование MainWindow.

**Добавить OCR engine**: Реализовать протокол `OCRBackend` в `rd_pipeline/ocr/backends/`, зарегистрировать в `factory.py`.

**Добавить API endpoint**: Создать route в `apps/remote_ocr_server/routes/`, подключить в `main.py`.

**Изменить БД**: Добавить миграцию в `database/migrations/`, задокументировать в `docs/DATABASE.md`.

## Конфигурация

Скопируйте `env.example` в `.env` и настройте:

Обязательные переменные `.env`:
- `SUPABASE_URL`, `SUPABASE_KEY` — База данных
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` — Хранилище
- `OPENROUTER_API_KEY` и/или `DATALAB_API_KEY` — OCR движки
- `REMOTE_OCR_BASE_URL` — URL сервера (по умолчанию: http://localhost:18000)
- `REDIS_URL` — Для сервера (по умолчанию: redis://redis:6379/0)

Docker-специфичные (опционально):
- `REMOTE_OCR_BIND_ADDR` — Адрес привязки (по умолчанию: 127.0.0.1)
- `REMOTE_OCR_PORT` — Внешний порт (по умолчанию: 18000)

## Стиль кода

Из `.cursorrules`: Будь максимально лаконичен. Код только в блоках кода. Изменения как минимальный diff. Без объяснений, если не спрошено. Если нужен текст — максимум 5 пунктов, каждый ≤ 12 слов.

**Git workflow**: После внесения изменений в код ВСЕГДА делай коммит и пуш. Сообщения коммитов пиши на русском языке.

## Язык

Все планы, ответы и объяснения генерируй на русском языке.
