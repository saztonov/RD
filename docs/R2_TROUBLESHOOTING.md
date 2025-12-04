# R2 Storage - Диагностика проблем

## Проверка логов

### 1. Файл логов

После запуска OCR проверьте файл:

```
logs/app.log
```

### 2. Поиск ошибок R2

```bash
# Windows PowerShell
Select-String -Path "logs\app.log" -Pattern "R2|upload_ocr_to_r2|R2Storage"

# Linux/Mac
grep -i "r2\|upload_ocr_to_r2\|r2storage" logs/app.log
```

### 3. Что искать в логах

**При успешной загрузке:**

```
=== OCRManager: Вызов метода _upload_to_r2 ===
Output directory: C:\...\output\project
=== ВЫЗОВ upload_ocr_to_r2() ===
=== Инициализация R2Storage ===
R2_ACCOUNT_ID: ✓
R2_ACCESS_KEY_ID: ✓
R2_SECRET_ACCESS_KEY: ✓
✅ R2Storage инициализирован (bucket: rd1, endpoint: https://...)
=== ЗАГРУЗКА РЕЗУЛЬТАТОВ OCR В R2 ===
Найдено файлов для загрузки: 15
[1/15] Загрузка: document.pdf
✅ Файл загружен в R2: ocr_results/project/document.pdf
...
✅ Все файлы успешно загружены в R2 bucket 'rd1'
```

**При ошибке конфигурации:**

```
R2_ACCOUNT_ID: ✗ НЕ УКАЗАН
R2_ACCESS_KEY_ID: ✗ НЕ УКАЗАН
❌ Не указаны обязательные параметры R2
```

**При ошибке доступа:**

```
❌ ClientError при загрузке в R2: AccessDenied - Access Denied
```

## Тестовый скрипт

Запустите тестовый скрипт для проверки R2:

```bash
python test_r2_upload.py
```

Скрипт проверит:
1. Инициализацию R2Storage
2. Доступ к bucket
3. Загрузку файла
4. Генерацию presigned URL
5. Удаление файла

## Типичные ошибки

### 1. "R2 Bucket: ✗ не настроен" в GUI

**Причина:** `.env` файл отсутствует или неполный

**Решение:**

1. Проверьте наличие `.env` в корне проекта:
   ```bash
   ls -la .env
   # или
   dir .env
   ```

2. Откройте `.env` и проверьте наличие всех параметров:
   ```env
   R2_ACCOUNT_ID=your_account_id
   R2_ACCESS_KEY_ID=your_access_key
   R2_SECRET_ACCESS_KEY=your_secret_key
   R2_BUCKET_NAME=rd1
   ```

3. Перезапустите приложение

### 2. "❌ Ошибка инициализации R2"

**Причина:** Не указаны обязательные параметры

**Решение:**

```env
# Обязательные параметры:
R2_ACCOUNT_ID=<ваш account ID>
R2_ACCESS_KEY_ID=<ваш access key>
R2_SECRET_ACCESS_KEY=<ваш secret key>

# Опциональные:
R2_BUCKET_NAME=rd1  # по умолчанию
```

### 3. "❌ ClientError: NoSuchBucket"

**Причина:** Bucket не существует

**Решение:**

1. Откройте [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Перейдите в **R2** → **Overview**
3. Создайте bucket `rd1`:
   - Нажмите **Create bucket**
   - Имя: `rd1`
   - Нажмите **Create bucket**

### 4. "❌ ClientError: AccessDenied"

**Причина:** Недостаточно прав или неверные credentials

**Решение:**

1. Проверьте правильность ключей в `.env`
2. Создайте новый API Token:
   - **R2** → **Manage R2 API Tokens**
   - **Create API Token**
   - **Permissions**: Object Read & Write
   - **Bucket**: rd1 (или All buckets)
3. Скопируйте новые credentials в `.env`
4. Перезапустите приложение

### 5. "❌ ClientError: InvalidAccessKeyId"

**Причина:** Неверный Access Key ID

**Решение:**

1. Проверьте что скопировали правильный ключ
2. Убедитесь что нет лишних пробелов в `.env`:
   ```env
   R2_ACCESS_KEY_ID=abc123xyz  # ✅ правильно
   R2_ACCESS_KEY_ID= abc123xyz # ❌ лишний пробел
   ```

### 6. "❌ ClientError: SignatureDoesNotMatch"

**Причина:** Неверный Secret Access Key

**Решение:**

1. Проверьте Secret Access Key в `.env`
2. Убедитесь что ключ скопирован полностью
3. Создайте новый API Token если потеряли старый

### 7. Логи показывают успех, но файлов нет в R2

**Причина:** Неправильный bucket или endpoint

**Решение:**

1. Проверьте логи:
   ```
   ✅ R2Storage инициализирован (bucket: rd1, endpoint: https://...)
   ```

2. Убедитесь что endpoint правильный:
   ```
   https://<account_id>.r2.cloudflarestorage.com
   ```

3. Проверьте bucket в Dashboard

### 8. "ConnectionError" или "Timeout"

**Причина:** Проблемы с сетью

**Решение:**

1. Проверьте интернет-соединение
2. Проверьте firewall/proxy настройки
3. Попробуйте позже (возможны временные проблемы)

## Диагностика шаг за шагом

### Шаг 1: Проверьте .env файл

```bash
# Windows PowerShell
Get-Content .env | Select-String "R2_"

# Linux/Mac
grep "R2_" .env
```

Должны быть строки:
```
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=rd1
```

### Шаг 2: Проверьте credentials

1. Откройте [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Перейдите в **R2** → **Overview**
3. Проверьте что Account ID совпадает
4. Проверьте что bucket `rd1` существует

### Шаг 3: Запустите тест

```bash
python test_r2_upload.py
```

Если тест прошел — R2 настроен правильно.

### Шаг 4: Запустите OCR с логированием

```bash
# Запустите приложение
python app/main.py

# В другом терминале следите за логами
tail -f logs/app.log
# или
Get-Content logs\app.log -Wait -Tail 50
```

### Шаг 5: Проверьте результат в R2

1. [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. **R2** → **Overview** → **rd1**
3. Папка `ocr_results/<project_name>/`

## Проверка переменных окружения в коде

Добавьте в `app/main.py` перед `MainWindow`:

```python
import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("R2 Configuration:")
print(f"R2_ACCOUNT_ID: {'✓' if os.getenv('R2_ACCOUNT_ID') else '✗'}")
print(f"R2_ACCESS_KEY_ID: {'✓' if os.getenv('R2_ACCESS_KEY_ID') else '✗'}")
print(f"R2_SECRET_ACCESS_KEY: {'✓' if os.getenv('R2_SECRET_ACCESS_KEY') else '✗'}")
print(f"R2_BUCKET_NAME: {os.getenv('R2_BUCKET_NAME', 'rd1')}")
print("=" * 60)
```

## Получение поддержки

Если проблема не решена:

1. **Соберите информацию:**
   - Версия Python: `python --version`
   - Версия boto3: `pip show boto3`
   - Содержимое логов: последние 50 строк из `logs/app.log`
   - Вывод `python test_r2_upload.py`

2. **Проверьте документацию:**
   - [R2_QUICK_START.md](R2_QUICK_START.md)
   - [R2_STORAGE_INTEGRATION.md](R2_STORAGE_INTEGRATION.md)
   - [Cloudflare R2 Docs](https://developers.cloudflare.com/r2/)

3. **Создайте Issue:**
   - Приложите логи (без секретных ключей!)
   - Опишите шаги для воспроизведения
   - Укажите что уже пробовали

## Безопасность

⚠️ **При отправке логов/скриншотов:**

- Удалите `R2_SECRET_ACCESS_KEY`
- Удалите `R2_ACCESS_KEY_ID`
- Можете оставить `R2_ACCOUNT_ID` (он не секретный)

---

**Обновлено:** 2025-12-02  
**Версия:** 1.0.0




