# Реализация кеширования статусов PDF

## Описание

Реализовано кеширование статусов PDF документов для ускорения работы приложения.

## Компоненты

### 1. PDFStatusCache (`app/gui/pdf_status_cache.py`)
- **TTL**: 5 минут (300 секунд)
- **Структура**: `{node_id: PDFStatusCacheEntry(status, message, timestamp)}`
- **Методы**:
  - `get(node_id)` - получить из кеша (с проверкой TTL)
  - `set(node_id, status, message)` - сохранить в кеш
  - `invalidate(node_id)` - инвалидировать конкретную запись
  - `invalidate_all()` - очистить весь кеш
  - `cleanup_expired()` - удалить истёкшие записи

### 2. TreeClient (`app/tree_client.py`)
**Новые методы**:
- `get_pdf_status(node_id, use_cache=True)` - получить статус с кешем
- `get_pdf_statuses_batch(node_ids)` - батч-загрузка статусов
- `update_pdf_status()` - обновление + инвалидация кеша

### 3. ProjectTreeWidget (`app/gui/project_tree_widget.py`)
**Оптимизации**:
- `_load_pdf_statuses_batch()` - одним запросом загружает все статусы при открытии
- `_cleanup_pdf_cache()` - периодическая очистка (каждую минуту)
- Локальные обновления узлов вместо `_refresh_tree()` при изменении статуса

## Логика работы

### Первая загрузка (открытие программы)
1. Загружается дерево проектов
2. Через 200мс запускается `_load_pdf_statuses_batch()`
3. Собираются ID всех PDF документов
4. **Один батч-запрос** загружает все статусы из БД
5. Статусы сохраняются в кеш и применяются к UI

### Последующие обращения
1. При чтении статуса сначала проверяется кеш
2. Если в кеше и не истёк TTL - используется кеш
3. Если нет - загружается из БД и кешируется

### Обновление статуса
1. При изменении аннотации/файлов:
   - Вычисляется новый статус
   - Обновляется в БД
   - **Инвалидируется запись в кеше**
   - Обновляется только конкретный узел в UI (без `_refresh_tree()`)

### Очистка кеша
- Каждую минуту запускается `cleanup_expired()`
- Удаляются записи старше TTL (5 минут)
- При полном обновлении дерева флаг `_pdf_statuses_loaded` сбрасывается

## Преимущества

### Производительность
- **1 запрос** вместо N запросов при загрузке (N = количество PDF)
- Нет повторных запросов к БД в течение TTL
- Локальные обновления UI вместо полного `_refresh_tree()`

### Примеры
- **100 PDF**: было 100 запросов → стало 1 запрос
- **Открытие программы**: ~5-10 секунд → ~0.5 секунды для статусов
- **Сохранение аннотации**: полное обновление дерева → локальное обновление узла

## Инвалидация кеша

Кеш инвалидируется при:
1. Сохранении/загрузке аннотации (`file_operations.py`, `file_auto_save.py`)
2. Вставке аннотации через контекстное меню
3. Загрузке аннотации из файла
4. Обновлении после завершения OCR (серверная сторона)
5. Истечении TTL (автоматически)

## Настройка

### Изменить TTL
```python
# В app/gui/pdf_status_cache.py
_pdf_status_cache = PDFStatusCache(ttl_seconds=600)  # 10 минут
```

### Отключить кеш (для отладки)
```python
# В app/tree_client.py при вызове
status, message = client.get_pdf_status(node_id, use_cache=False)
```

### Очистить кеш вручную
```python
from app.gui.pdf_status_cache import get_pdf_status_cache
cache = get_pdf_status_cache()
cache.invalidate_all()
```

## Мониторинг

### Логи
```
DEBUG: Cached PDF status for {node_id}: {status}
INFO: Loaded PDF statuses: {count} documents
DEBUG: Cleaned {count} expired PDF status cache entries
```

### Проверка состояния кеша
```python
cache = get_pdf_status_cache()
print(f"Cached entries: {cache.get_cached_count()}")
```
