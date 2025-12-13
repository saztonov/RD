# Cloudflare R2 Storage Integration

Автоматическая загрузка результатов OCR в Cloudflare R2 Object Storage.

⚡ **Быстрый старт:** [R2_QUICK_START.md](R2_QUICK_START.md)

## Возможности

- ✅ Автоматическая загрузка после OCR
- ✅ S3-совместимый API (boto3)
- ✅ Загрузка всей структуры (PDF, JSON, crops, MD)
- ✅ Bucket: `rd1`
- ✅ Конфигурация через `.env`
- ✅ Индикатор в GUI (настроен/не настроен)

## Установка

### 1. Установите boto3

```bash
pip install boto3
```

### 2. Настройте .env

Создайте `.env` файл в корне проекта:

```env
# Cloudflare R2 Object Storage
R2_ACCOUNT_ID=your_cloudflare_account_id
R2_ACCESS_KEY_ID=your_r2_access_key_id
R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
R2_BUCKET_NAME=rd1
```

### 3. Получите ключи R2

1. Войдите в [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Перейдите в **R2** → **Overview**
3. Создайте bucket `rd1` (если не существует)
4. Перейдите в **R2** → **Manage R2 API Tokens**
5. Нажмите **Create API Token**
6. Выберите:
   - **Permissions**: Object Read & Write
   - **Bucket**: `rd1` (или All buckets)
7. Скопируйте:
   - **Access Key ID** → `R2_ACCESS_KEY_ID`
   - **Secret Access Key** → `R2_SECRET_ACCESS_KEY`
   - **Account ID** → `R2_ACCOUNT_ID`

## Использование

### Автоматическая загрузка

После завершения OCR результаты **автоматически загружаются** в R2:

1. Запустите OCR через GUI (Ctrl+R)
2. Дождитесь завершения
3. Результаты сохранятся локально И загрузятся в R2

### Структура в R2

```
rd1/
└── ocr_results/
    └── <project_name>/
        ├── document.pdf
        ├── annotation.json
        ├── document.md
        └── crops/
            ├── page0_block123.png
            ├── page0_block456.png
            └── ...
```

### Программное использование

```python
from rd_core.r2_storage import R2Storage, upload_ocr_to_r2

# Вариант 1: Быстрая загрузка
upload_ocr_to_r2("output/my_project", project_name="my_project")

# Вариант 2: Полный контроль
r2 = R2Storage()

# Загрузить файл
r2.upload_file("local/file.pdf", "remote/path/file.pdf")

# Загрузить директорию
r2.upload_directory("output/project", remote_prefix="ocr_results/project")

# Список объектов
files = r2.list_objects(prefix="ocr_results/")

# Временная ссылка (1 час)
url = r2.generate_presigned_url("ocr_results/project/document.pdf", expiration=3600)
```

## API Reference

### R2Storage

```python
class R2Storage:
    def __init__(
        self,
        account_id: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None
    )
```

**Параметры загружаются из `.env` если не указаны явно.**

### Методы

#### upload_file

```python
def upload_file(
    self,
    local_path: str,
    remote_key: str,
    content_type: Optional[str] = None
) -> bool
```

Загрузить один файл.

#### upload_directory

```python
def upload_directory(
    self,
    local_dir: str,
    remote_prefix: str = "",
    recursive: bool = True
) -> tuple[int, int]
```

Загрузить директорию. Возвращает `(успешно, ошибок)`.

#### upload_ocr_results

```python
def upload_ocr_results(
    self,
    output_dir: str,
    project_name: Optional[str] = None
) -> bool
```

Загрузить результаты OCR с автоматическим префиксом `ocr_results/<project_name>`.

#### list_objects

```python
def list_objects(self, prefix: str = "") -> list[str]
```

Список ключей объектов в bucket.

#### delete_object

```python
def delete_object(self, remote_key: str) -> bool
```

Удалить объект.

#### generate_presigned_url

```python
def generate_presigned_url(
    self,
    remote_key: str,
    expiration: int = 3600
) -> Optional[str]
```

Создать временную ссылку на объект (по умолчанию 1 час).

## Логирование

Все операции логируются:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

Пример вывода:

```
INFO:app.r2_storage:R2Storage инициализирован (bucket: rd1)
INFO:app.r2_storage:Файл загружен в R2: ocr_results/project/document.pdf
INFO:app.r2_storage:Загрузка завершена: 15 успешно, 0 ошибок
```

## Troubleshooting

### Ошибка: "Не указаны обязательные параметры R2"

**Решение:** Проверьте `.env` файл:

```bash
# Убедитесь что файл существует
ls -la .env

# Проверьте содержимое
cat .env
```

### Ошибка: "Access Denied"

**Решение:**

1. Проверьте права API токена (Object Read & Write)
2. Убедитесь что bucket `rd1` существует
3. Проверьте правильность `R2_ACCESS_KEY_ID` и `R2_SECRET_ACCESS_KEY`

### Ошибка: "Connection timeout"

**Решение:**

1. Проверьте интернет-соединение
2. Убедитесь что `R2_ENDPOINT_URL` корректен
3. Проверьте firewall/proxy настройки

### Загрузка не происходит

**Решение:**

1. Проверьте логи: `logs/app.log`
2. Убедитесь что `.env` файл загружен
3. Проверьте что `boto3` установлен: `pip install boto3`

## Безопасность

⚠️ **Важно:**

- Не коммитьте `.env` файл в git
- Используйте `.gitignore`:
  ```
  .env
  .env.local
  ```
- Храните ключи в безопасном месте
- Используйте bucket-scoped tokens (минимальные права)

## Ссылки

- [Cloudflare R2 Documentation](https://developers.cloudflare.com/r2/)
- [boto3 with R2](https://developers.cloudflare.com/r2/examples/aws/boto3/)
- [R2 API Tokens](https://developers.cloudflare.com/r2/api/tokens/)

---

**Версия:** 1.0.0  
**Требования:** boto3 >= 1.28.0, python-dotenv >= 1.0.0

