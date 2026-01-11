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

#### Production
```bash
cp env.example .env              # Настроить переменные окружения
docker compose up -d --build     # Запуск (слушает 127.0.0.1:18000)
```

Для работы за nginx, добавить в `.env`:
```env
REMOTE_OCR_BIND_ADDR=127.0.0.1
REMOTE_OCR_PORT=18000
```

#### Development (с hot reload)
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

#### Без Docker
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

Скопируйте `env.example` в `.env` и настройте переменные.

См. полный список переменных в [env.example](env.example).

## Документация

- [DATABASE.md](docs/DATABASE.md) — схема БД
- [CLAUDE.md](CLAUDE.md) — контекст для AI
