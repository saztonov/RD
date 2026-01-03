# Улучшения безопасности - Вариант 2

## ✅ Реализовано

### 1. API Proxy Architecture

**Было (небезопасно):**
```
Desktop Client (.exe)
  ├─ SUPABASE_KEY внедрен в exe
  ├─ R2_ACCESS_KEY внедрен в exe
  ├─ R2_SECRET_ACCESS_KEY внедрен в exe
  ├─ OPENROUTER_API_KEY внедрен в exe
  └─ DATALAB_API_KEY внедрен в exe
```

**Стало (безопасно):**
```
Desktop Client (.exe)
  └─ только REMOTE_OCR_API_KEY (в .env)

Remote OCR Server
  ├─ SUPABASE_KEY (на сервере)
  ├─ R2_ACCESS_KEY (на сервере)
  ├─ R2_SECRET_ACCESS_KEY (на сервере)
  ├─ OPENROUTER_API_KEY (на сервере)
  └─ DATALAB_API_KEY (на сервере)
```

### 2. Новые компоненты

#### 2.1 UnifiedClient (`app/unified_client.py`)
- Единый клиент для Tree и Storage операций
- Все запросы через Remote OCR Server API
- Совместимый интерфейс с TreeClient/R2Storage

#### 2.2 API Routes на сервере

**Tree API** (`services/remote_ocr/server/routes/tree.py`):
- `GET /api/tree/nodes/root` - корневые проекты
- `GET /api/tree/nodes/{id}` - получить узел
- `GET /api/tree/nodes/{id}/children` - дочерние узлы
- `POST /api/tree/nodes` - создать узел
- `PATCH /api/tree/nodes/{id}` - обновить узел
- `DELETE /api/tree/nodes/{id}` - удалить узел
- `GET /api/tree/stage-types` - типы стадий
- `GET /api/tree/section-types` - типы разделов
- `GET /api/tree/image-categories` - категории изображений
- и др.

**Storage API** (`services/remote_ocr/server/routes/storage.py`):
- `GET /api/storage/exists/{key}` - проверка существования
- `GET /api/storage/download/{key}` - скачать файл (presigned URL)
- `GET /api/storage/download-text/{key}` - скачать текст
- `POST /api/storage/upload/{key}` - загрузить файл
- `POST /api/storage/upload-text` - загрузить текст
- `DELETE /api/storage/delete/{key}` - удалить объект
- `POST /api/storage/delete-batch` - батчевое удаление
- `GET /api/storage/list/{prefix}` - список файлов
- и др.

#### 2.3 Безопасная сборка (`build.py`)
```python
SAFE_ENV_VARS = {
    'REMOTE_OCR_BASE_URL',  # Только публичные переменные
}
```

Секреты больше НЕ внедряются в exe файл!

### 3. Аутентификация

Все API endpoints защищены `X-API-Key` заголовком:
```python
headers = {"X-API-Key": os.getenv("REMOTE_OCR_API_KEY")}
```

### 4. Документация

- `docs/MIGRATION_TO_UNIFIED_CLIENT.md` - инструкции по миграции
- `test_unified_client.py` - автоматические тесты

## Инструкции по развертыванию

### Шаг 1: Обновить сервер

```bash
cd services/remote_ocr

# Проверить что новые роуты зарегистрированы
grep "tree_router\|storage_router" server/main.py

# Перезапустить сервер
docker compose restart
```

### Шаг 2: Тест новых API

```bash
# Health check
curl http://localhost:8000/health

# Tree API
curl http://localhost:8000/api/tree/nodes/root \
  -H "X-API-Key: your_key"

# Storage API
curl http://localhost:8000/api/storage/exists/test.pdf \
  -H "X-API-Key: your_key"
```

### Шаг 3: Миграция клиента

**Опция A: Постепенная миграция** (рекомендуется)

Использовать `UnifiedClient` только для новых функций:
```python
from app.unified_client import UnifiedClient
from app.tree_client import TreeClient  # Старый клиент

# Новый код использует UnifiedClient
client = UnifiedClient()

# Старый код продолжает работать
legacy_client = TreeClient()
```

**Опция B: Полная миграция**

Заменить все использования:
```bash
# Поиск использований TreeClient
grep -r "TreeClient()" app/gui/

# Поиск использований R2Storage
grep -r "R2Storage()" app/gui/

# Замена импортов
# from app.tree_client import TreeClient
# from rd_core.r2_storage import R2Storage
# →
# from app.unified_client import UnifiedClient
```

### Шаг 4: Пересборка exe

```bash
# Сборка с новыми настройками безопасности
python build.py

# Проверка - секреты НЕ должны быть в exe
strings dist/CoreStructure.exe | grep -i "supabase\|openrouter\|datalab"
# Не должно ничего найти!

# Создать .env рядом с exe
cat > dist/.env << EOF
REMOTE_OCR_BASE_URL=https://ocr.fvds.ru
REMOTE_OCR_API_KEY=your_secret_key_here
EOF
```

### Шаг 5: Тестирование

```bash
# Автоматические тесты
python test_unified_client.py

# Ожидаемый вывод:
# Health Check.................... ✅ PASSED
# Tree Operations................. ✅ PASSED
# Storage Operations.............. ✅ PASSED
# Batch Operations................ ✅ PASSED
```

## Ротация ключей (если exe уже распространялся)

### Критично! Если старый exe с секретами уже был выпущен:

1. **Сменить все API ключи:**
   - OpenRouter: https://openrouter.ai/keys
   - Datalab: https://www.datalab.to/settings
   - Supabase: Project Settings → API → Rotate keys
   - R2: Cloudflare Dashboard → R2 → Manage R2 API Tokens
   - REMOTE_OCR_API_KEY: сгенерировать новый

2. **Обновить .env на сервере:**
   ```bash
   docker compose down
   # Обновить .env с новыми ключами
   docker compose up -d
   ```

3. **Пересобрать клиент:**
   ```bash
   python build.py
   # Распространить новый exe с инструкциями по .env
   ```

4. **Уведомить пользователей:**
   ```
   Внимание! Обновление безопасности.
   
   1. Скачайте новую версию CoreStructure.exe
   2. Создайте файл .env рядом с exe:
   
   REMOTE_OCR_BASE_URL=https://ocr.fvds.ru
   REMOTE_OCR_API_KEY=<новый_ключ>
   
   Старые версии перестанут работать после [дата].
   ```

## Преимущества новой архитектуры

### Безопасность
- ✅ Секреты только на сервере
- ✅ Невозможно извлечь из exe
- ✅ Единая точка ротации ключей
- ✅ Централизованный API ключ для клиентов

### Управление
- ✅ Логирование всех запросов на сервере
- ✅ Rate limiting на API уровне
- ✅ Единая точка аудита
- ✅ Возможность блокировки скомпрометированных клиентов

### Масштабируемость
- ✅ Кеширование на сервере
- ✅ Оптимизация батчевых запросов
- ✅ Presigned URLs для больших файлов
- ✅ Легко добавить новые endpoints

### Мониторинг
- ✅ Все операции видны в логах сервера
- ✅ Метрики использования API
- ✅ Детекция аномального поведения

## Производительность

### Потенциальные задержки:
- Дополнительный network hop: +10-50ms
- Сериализация/десериализация: +1-5ms

### Оптимизации:
- Presigned URLs для download (редирект без прокси)
- HTTP/2 connection pooling
- Кеширование справочников на клиенте
- Батчевые запросы

### Измерения:
```python
# Сравнение производительности
import time

# Старый подход (прямой доступ)
start = time.time()
from app.tree_client import TreeClient
client = TreeClient()
nodes = client.get_root_nodes()
print(f"Прямой доступ: {time.time() - start:.3f}s")

# Новый подход (через API)
start = time.time()
from app.unified_client import UnifiedClient
client = UnifiedClient()
nodes = client.get_root_nodes()
print(f"Через API: {time.time() - start:.3f}s")
```

## Откат

Если нужно временно вернуться к старой схеме:

1. **На клиенте:**
   ```python
   # Использовать старые клиенты
   from app.tree_client import TreeClient
   from rd_core.r2_storage import R2Storage
   ```

2. **В .env клиента:**
   ```env
   # Вернуть все секреты
   SUPABASE_URL=...
   SUPABASE_KEY=...
   R2_ACCOUNT_ID=...
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   ```

3. **Пересобрать с секретами (временно!):**
   ```python
   # build.py - убрать фильтрацию SAFE_ENV_VARS
   # НО ЭТО НЕБЕЗОПАСНО!
   ```

## Контрольный чек-лист

- [x] Создан `UnifiedClient` с совместимым интерфейсом
- [x] Реализован Tree API на сервере (`/api/tree/*`)
- [x] Реализован Storage API на сервере (`/api/storage/*`)
- [x] Обновлен `build.py` для безопасной сборки
- [x] Создана документация по миграции
- [x] Созданы автоматические тесты
- [ ] Протестирован на реальных данных
- [ ] Измерена производительность
- [ ] Обновлен GUI код (постепенная миграция)
- [ ] Пересобран exe и протестирован end-to-end
- [ ] Подготовлены инструкции для пользователей
- [ ] Ротированы старые ключи (если exe распространялся)

## Следующие шаги

1. **Тестирование:** `python test_unified_client.py`
2. **Постепенная миграция GUI:** начать с некритичных компонентов
3. **Мониторинг:** добавить метрики на сервере
4. **Документация пользователей:** инструкция по setup .env
5. **Релиз:** пересборка exe, распространение, уведомления
