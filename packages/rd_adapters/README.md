# rd_adapters

**Layer 2** — Инфраструктурные адаптеры.

Содержит адаптеры для внешних сервисов (хранилище, кэширование).

## Зависимости

- `rd_domain` — доменные модели
- boto3 / aioboto3 — S3-совместимое API
- botocore — конфигурация AWS

## Модули

### storage/
Адаптеры для Cloudflare R2 (S3-совместимое хранилище).

#### Экспорты

```python
from rd_adapters.storage import (
    # Протоколы
    StoragePort, AsyncStoragePort,
    # Конфиг и утилиты
    R2Config, CONTENT_TYPES, guess_content_type,
    # Синхронная реализация
    R2SyncStorage,
    # Асинхронная реализация
    R2AsyncStorage, R2AsyncStorageSync,
    # Обработка ошибок
    StorageErrorCode, StorageErrorResult,
    classify_client_error, handle_download_error, handle_upload_error,
)
```

#### Протоколы

```python
from rd_adapters.storage import StoragePort, AsyncStoragePort

class StoragePort(Protocol):
    def upload_file(self, local_path: str, remote_key: str) -> bool: ...
    def download_file(self, remote_key: str, local_path: str) -> bool: ...
    def upload_text(self, content: str, remote_key: str) -> bool: ...
    def download_text(self, remote_key: str) -> Optional[str]: ...
    def exists(self, remote_key: str) -> bool: ...
    def delete_object(self, remote_key: str) -> bool: ...
    def list_objects(self, prefix: str) -> List[str]: ...
    def generate_presigned_url(self, remote_key: str, expiration: int = 3600) -> Optional[str]: ...
```

#### Синхронный клиент

```python
from rd_adapters.storage import R2SyncStorage

# Создание из переменных окружения
storage = R2SyncStorage.from_env()

# Операции
storage.upload_file("local.pdf", "remote/path/file.pdf")
storage.download_file("remote/path/file.pdf", "local.pdf")
content = storage.download_text("remote/path/data.json")
exists = storage.exists("remote/path/file.pdf")
url = storage.generate_presigned_url("remote/path/file.pdf", expiration=3600)
```

#### Асинхронный клиент с синхронной обёрткой

```python
from rd_adapters.storage import R2AsyncStorageSync

# Создание
storage = R2AsyncStorageSync.from_env()

# Те же методы, что и у синхронного
storage.upload_file("local.pdf", "remote/path/file.pdf")

# Presigned URL для PUT (загрузка)
put_url = storage.generate_presigned_put_url(
    "remote/path/file.pdf",
    content_type="application/pdf",
    expiration=900
)
```

### storage/caching/
Кэширование метаданных.

```python
from rd_adapters.storage.caching import MetadataCache

cache = MetadataCache(max_size=1000)
cache.set("key", {"size": 1024, "modified": "2024-01-01"})
metadata = cache.get("key")
cache.invalidate("key")
```

### storage/errors.py
Обработка ошибок хранилища.

```python
from rd_adapters.storage import (
    StorageErrorCode,
    StorageErrorResult,
    classify_client_error,
    handle_download_error,
    handle_upload_error,
)

# Коды ошибок
StorageErrorCode.NOT_FOUND      # Файл не найден
StorageErrorCode.ACCESS_DENIED  # Доступ запрещён
StorageErrorCode.NETWORK        # Сетевая ошибка
StorageErrorCode.UNKNOWN        # Неизвестная ошибка

# Обработка ошибок
result = handle_download_error(exception, "path/to/file")
if result.code == StorageErrorCode.NOT_FOUND:
    print("File not found")
```

## Конфигурация

Переменные окружения для R2:

```env
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=your_bucket
```

## Правила импорта

rd_adapters — инфраструктурный слой:
- Зависит от `rd_domain`
- НЕ импортирует из `apps/`
- Может импортироваться только `apps/`

```
rd_domain (Layer 0)
    ↑
rd_pipeline (Layer 1)
    ↑
rd_adapters (Layer 2)  ← вы здесь
    ↑
apps/ (Application Layer)
```
