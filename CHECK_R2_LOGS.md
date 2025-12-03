# Проверка логов R2 Storage

## Быстрая проверка

### 1. Запустите тест R2

```bash
python test_r2_upload.py
```

**Если тест успешен** → R2 настроен правильно  
**Если тест провален** → смотрите ошибки в выводе

### 2. Проверьте логи после OCR

Откройте файл:
```
logs/app.log
```

Найдите строки с ключевыми словами:
- `R2Storage`
- `upload_ocr_to_r2`
- `_upload_to_r2`

### 3. Типичные ошибки в логах

**✅ Успешная загрузка:**
```
=== OCRManager: Вызов метода _upload_to_r2 ===
=== Инициализация R2Storage ===
R2_ACCOUNT_ID: ✓
R2_ACCESS_KEY_ID: ✓
R2_SECRET_ACCESS_KEY: ✓
✅ R2Storage инициализирован (bucket: rd1)
Найдено файлов для загрузки: 15
✅ Файл загружен в R2: ocr_results/project/document.pdf
✅ Все файлы успешно загружены в R2 bucket 'rd1'
```

**❌ Не настроен .env:**
```
R2_ACCOUNT_ID: ✗ НЕ УКАЗАН
R2_ACCESS_KEY_ID: ✗ НЕ УКАЗАН
❌ Не указаны обязательные параметры R2
```

**❌ Неверные credentials:**
```
❌ ClientError при загрузке в R2: InvalidAccessKeyId
❌ ClientError при загрузке в R2: SignatureDoesNotMatch
```

**❌ Bucket не существует:**
```
❌ ClientError при загрузке в R2: NoSuchBucket
```

**❌ Нет прав доступа:**
```
❌ ClientError при загрузке в R2: AccessDenied
```

## Детальная диагностика

Смотрите: [`docs/R2_TROUBLESHOOTING.md`](docs/R2_TROUBLESHOOTING.md)

## Что делать если логи показывают ошибку

1. **"НЕ УКАЗАН"** → Заполните `.env` файл (см. `.env.template`)

2. **"InvalidAccessKeyId"** → Проверьте `R2_ACCESS_KEY_ID` в `.env`

3. **"SignatureDoesNotMatch"** → Проверьте `R2_SECRET_ACCESS_KEY` в `.env`

4. **"NoSuchBucket"** → Создайте bucket `rd1` в Cloudflare Dashboard

5. **"AccessDenied"** → Создайте новый API Token с правами Read & Write

## Быстрая настройка

См.: [`docs/R2_QUICK_START.md`](docs/R2_QUICK_START.md)



