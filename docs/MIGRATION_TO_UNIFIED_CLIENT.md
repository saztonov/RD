# Миграция на UnifiedClient

## Обзор изменений

Старая архитектура (небезопасно):
```
Desktop Client → Supabase (прямой доступ)
                → R2 Storage (прямой доступ)
                → Remote OCR Server

Секреты в клиенте: SUPABASE_KEY, R2_ACCESS_KEY, R2_SECRET_ACCESS_KEY
```

Новая архитектура (безопасно):
```
Desktop Client → Remote OCR Server API → Supabase
                                       → R2 Storage

Секреты в клиенте: только REMOTE_OCR_API_KEY
```

## Что изменилось

### 1. Новый UnifiedClient
- Заменяет `TreeClient` и `R2Storage`
- Все операции через API сервер
- Совместимый интерфейс

### 2. Новые API endpoints на сервере
- `/api/tree/*` - операции с деревом проектов
- `/api/storage/*` - операции с R2 хранилищем

### 3. Безопасная сборка
- `build.py` не внедряет секреты в exe
- Секреты читаются из `.env` рядом с exe

## Миграция кода

### Было (старый TreeClient):
```python
from app.tree_client import TreeClient

client = TreeClient()
node = client.get_node(node_id)
```

### Стало (новый UnifiedClient):
```python
from app.unified_client import UnifiedClient

client = UnifiedClient()
node = client.get_node(node_id)
```

### Было (старый R2Storage):
```python
from rd_core.r2_storage import R2Storage

r2 = R2Storage()
r2.upload_file(local_path, r2_key)
```

### Стало (новый UnifiedClient):
```python
from app.unified_client import UnifiedClient

client = UnifiedClient()
client.upload_file(local_path, r2_key)
```

## Переменные окружения

### Для клиента (.env рядом с exe):
```env
# Обязательные
REMOTE_OCR_BASE_URL=https://ocr.fvds.ru
REMOTE_OCR_API_KEY=your_secret_key

# Больше НЕ нужны (секреты на сервере):
# SUPABASE_URL
# SUPABASE_KEY
# R2_ACCOUNT_ID
# R2_ACCESS_KEY_ID
# R2_SECRET_ACCESS_KEY
# OPENROUTER_API_KEY
# DATALAB_API_KEY
```

### Для сервера (.env):
```env
# Сервер имеет ВСЕ секреты
SUPABASE_URL=...
SUPABASE_KEY=...
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
OPENROUTER_API_KEY=...
DATALAB_API_KEY=...
REMOTE_OCR_API_KEY=...  # Для аутентификации клиентов
REDIS_URL=redis://redis:6379/0
```

## Сборка приложения

```bash
# Старая сборка (небезопасно - внедряла все секреты)
python build.py

# Новая сборка (безопасно - только публичные переменные)
python build.py

# После сборки создать .env рядом с exe:
dist/
  ├── CoreStructure.exe
  └── .env  ← REMOTE_OCR_BASE_URL и REMOTE_OCR_API_KEY
```

## Пошаговая миграция GUI кода

1. **Замена импортов:**
   ```python
   # Было
   from app.tree_client import TreeClient
   from rd_core.r2_storage import R2Storage
   
   # Стало
   from app.unified_client import UnifiedClient
   ```

2. **Замена инициализации:**
   ```python
   # Было
   client = TreeClient()
   r2 = R2Storage()
   
   # Стало
   client = UnifiedClient()  # Заменяет оба!
   ```

3. **Адаптация кода:**
   - Tree методы: без изменений (`client.get_node()`)
   - Storage методы: `r2.upload_file()` → `client.upload_file()`

## Проверка миграции

### Сервер:
```bash
# Запустить сервер
docker compose up

# Проверить новые endpoints
curl http://localhost:8000/api/tree/nodes/root -H "X-API-Key: your_key"
curl http://localhost:8000/api/storage/exists/test.pdf -H "X-API-Key: your_key"
```

### Клиент:
```python
from app.unified_client import UnifiedClient

client = UnifiedClient()
assert client.is_available(), "API недоступен!"

# Тест tree API
roots = client.get_root_nodes()
print(f"Проекты: {len(roots)}")

# Тест storage API
exists = client.exists("some/file.pdf")
print(f"Файл существует: {exists}")
```

## Преимущества новой архитектуры

✅ **Безопасность:**
- Секреты только на сервере
- Невозможно извлечь из exe
- Единая точка ротации ключей

✅ **Централизация:**
- Все запросы через API
- Логирование на сервере
- Rate limiting

✅ **Масштабируемость:**
- Легко добавить кеширование
- Можно оптимизировать батчевые запросы
- Единая точка аудита

## Откат (если нужно)

Старый код остался без изменений:
```python
# Можно использовать старые клиенты параллельно
from app.tree_client import TreeClient  # Старый
from app.unified_client import UnifiedClient  # Новый
```

## FAQ

**Q: Что делать с уже распространенными exe?**
A: Сменить все API ключи (OpenRouter, Datalab, R2, Supabase), пересобрать, обновить пользователям.

**Q: Производительность пострадает?**
A: Минимально. Можно кешировать на сервере и использовать presigned URLs для больших файлов.

**Q: Можно ли использовать старый подход локально?**
A: Да, для разработки можно оставить прямой доступ через `.env`.
