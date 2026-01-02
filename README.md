# Core Structure

**Версия:** 0.1  
**Статус:** Alpha  
**Лицензия:** MIT

**Описание:** Система структурного анализа и обработки документов с поддержкой удалённого OCR, иерархического управления проектами и интеллектуальной разметки блоков.

Desktop-клиент для аннотирования PDF с удалённым OCR и управлением проектами.

📚 **[Документация](docs/)** | 🚀 **[Запуск](docs/ЗАПУСК.md)**

---

## 📋 Содержание

- [Функциональность](#функциональность)
- [Установка](#установка)
- [Запуск](#запуск)
- [Структура проекта](#структура-проекта)
- [Использование](#использование)
- [Документация](#документация)

---

## Функциональность

- ✅ Просмотр и аннотирование PDF (прямоугольники и полигоны)
- ✅ **Remote OCR** — распределённая обработка через FastAPI + Celery
- ✅ **Tree Projects** — иерархическое управление проектами
- ✅ Сохранение в R2 Storage и Supabase
- ✅ OCR движки: OpenRouter, Datalab
- ✅ Экспорт в Markdown

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

### Remote OCR сервер

**Docker (рекомендуется):**
```bash
docker compose -f docker-compose.remote-ocr.dev.yml up --build
```

Запускает 3 сервиса:
- `web` — FastAPI сервер (порт 8000)
- `redis` — Redis для Celery
- `worker` — Celery воркер

**Без Docker:**
```bash
# Терминал 1: Redis
redis-server

# Терминал 2: API сервер
cd services/remote_ocr
uvicorn services.remote_ocr.server.main:app --host 0.0.0.0 --port 8000 --reload

# Терминал 3: Celery воркер
celery -A services.remote_ocr.server.celery_app worker --loglevel=info --concurrency=1
```

**Проверка:**
```bash
curl http://localhost:8000/health
curl http://localhost:8000/queue
```

## Структура проекта

```
├── app/                    # Desktop клиент (PySide6)
│   ├── main.py            # Точка входа
│   ├── remote_ocr_client.py  # HTTP клиент
│   ├── tree_client.py     # Supabase клиент
│   └── gui/               # Интерфейс
├── rd_core/               # Ядро (модели, OCR, R2)
│   ├── models.py
│   ├── pdf_utils.py
│   ├── r2_storage.py
│   └── ocr/               # OCR движки
├── services/remote_ocr/   # Remote OCR сервер
│   └── server/            # FastAPI + Celery
├── database/              # Схема БД
└── docs/                  # Документация
```

Подробнее: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)


## Использование

1. **Открытие PDF:** `File → Open PDF`
2. **Разметка блоков:** Рисуйте мышью (прямоугольники) или `Ctrl+P` (полигоны)
3. **Remote OCR:** Выделите блоки → `Remote OCR → Send to OCR`
4. **Tree Projects:** `View → Tree Projects` → управление иерархией проектов
5. **Сохранение:** `File → Save Annotation` или `File → Save Draft to Server`

Подробнее: [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)

## Сборка в EXE

```bash
python build.py
```

Результат: `dist/CoreStructure.exe`

## Документация

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — техническая документация и архитектура
- [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) — руководство разработчика
- [`docs/DATABASE.md`](docs/DATABASE.md) — схема базы данных (Supabase)
- [`docs/REMOTE_OCR_SERVER.md`](docs/REMOTE_OCR_SERVER.md) — документация Remote OCR сервера
- [`docs/ЗАПУСК.md`](docs/ЗАПУСК.md) — быстрые команды запуска

---

## О продукте

**Название:** Core Structure  
**Версия:** 0.1  
**Статус:** Alpha  
**Лицензия:** MIT  

**Технологии:**  
- **Python:** 3.11+  
- **GUI:** PySide6  
- **Storage:** Cloudflare R2 + Supabase  
- **OCR:** OpenRouter, Datalab  
- **Queue:** Celery + Redis
