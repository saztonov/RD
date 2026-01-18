# Core Structure

Desktop-клиент для аннотирования PDF с удалённым OCR.

**Стек:** Python 3.11+, PySide6, FastAPI, Celery, Redis, Supabase, Cloudflare R2

## Quick Start

```bash
# Установка
pip install -r requirements.txt

# Запуск клиента
python apps/rd_desktop/main.py

# Сборка EXE
python build.py  # → dist/CoreStructure.exe
```

## OCR Сервер

### Docker (рекомендуется)
```bash
cp env.example .env
docker compose up -d --build     # Production
# или
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build  # Development
```

### Без Docker
```bash
redis-server                                                                      # Terminal 1
uvicorn apps.remote_ocr_server.main:app --host 0.0.0.0 --port 8000 --reload      # Terminal 2
celery -A apps.remote_ocr_server.celery_app worker --loglevel=info --concurrency=1  # Terminal 3
```

## Конфигурация

Скопируйте `env.example` в `.env` — см. [CLAUDE.md](CLAUDE.md) для списка переменных.

## Документация

- [CLAUDE.md](CLAUDE.md) — архитектура, команды, расширение
- [docs/DATABASE.md](docs/DATABASE.md) — схема БД
- [docs/INVARIANTS.md](docs/INVARIANTS.md) — архитектурные инварианты
