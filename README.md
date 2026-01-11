# Core Structure

Desktop-клиент для аннотирования PDF с удалённым OCR.

**Стек:** Python 3.11+, PySide6, FastAPI, Celery, Redis, Supabase, Cloudflare R2

## Установка

```bash
pip install -r requirements.txt
```

## Запуск

### Клиент
```bash
python app/main.py
```

### Сервер OCR
```bash
docker compose -f docker-compose.remote-ocr.dev.yml up --build
```

Или без Docker:
```bash
redis-server                                                              # Terminal 1
uvicorn services.remote_ocr.server.main:app --host 0.0.0.0 --port 8000   # Terminal 2
celery -A services.remote_ocr.server.celery_app worker --loglevel=info   # Terminal 3
```

### Сборка EXE
```bash
python build.py  # → dist/CoreStructure.exe
```

## Конфигурация (.env)

```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key

# R2 Storage
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=rd1

# OCR
OPENROUTER_API_KEY=your_key
DATALAB_API_KEY=your_key

# Server
REMOTE_OCR_BASE_URL=http://localhost:8000
REDIS_URL=redis://localhost:6379/0
```

## Документация

- [DATABASE.md](docs/DATABASE.md) — схема БД
- [CLAUDE.md](CLAUDE.md) — контекст для AI
