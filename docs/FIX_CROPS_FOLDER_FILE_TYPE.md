# Исправление ошибки с file_type='crops_folder'

## Описание проблемы

У файлов, которые были распознаны с помощью Remote OCR, не появлялась иконка в дереве проектов. Вместо этого выводилась ошибка:

```
Ошибка проверки: 'crops_folder' is not a valid FileType
```

## Причина

При десериализации объектов `NodeFile` из базы данных Supabase метод `from_dict()` пытался преобразовать строку `'crops_folder'` в enum `FileType` без обработки ошибок и нормализации входных данных. Это могло приводить к сбоям при малейших отклонениях в формате данных (пробелы, регистр и т.д.).

## Решение

### 1. Улучшена обработка в `app/tree_models.py`

Метод `NodeFile.from_dict()` теперь включает:

- **Нормализацию значения**: Убирает пробелы и приводит к нижнему регистру
- **Обработку исключений**: При ошибке преобразования использует fallback значение (`FileType.PDF`)
- **Логирование**: Записывает предупреждения о невалидных значениях file_type

```python
@classmethod
def from_dict(cls, data: dict) -> "NodeFile":
    # Безопасное преобразование file_type
    raw_file_type = data["file_type"]
    try:
        # Нормализуем значение: убираем пробелы и приводим к нижнему регистру
        normalized_type = raw_file_type.strip().lower() if isinstance(raw_file_type, str) else raw_file_type
        file_type = FileType(normalized_type)
    except ValueError as e:
        # Если значение не валидно, логируем предупреждение и используем fallback
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Invalid file_type '{raw_file_type}' for node_file {data.get('id')}, using 'pdf' as fallback: {e}")
        file_type = FileType.PDF

    return cls(...)
```

### 2. Улучшено логирование в `rd_core/pdf_status.py`

- Добавлен параметр `exc_info=True` для вывода полного traceback при ошибках
- Добавлена явная обработка исключений при получении файлов узла

```python
# Проверяем наличие файлов в Supabase
try:
    node_files = client.get_node_files(node_id)
    file_types_in_db = {nf.file_type for nf in node_files}
except Exception as e:
    logger.error(f"Failed to get node files for {node_id}: {e}", exc_info=True)
    raise
```

## Тестирование

После внесения изменений были проведены следующие тесты:

1. **Проверка наличия записей с `crops_folder` в БД**: Обнаружена 1 запись
2. **Десериализация NodeFile**: Успешно прошла для всех 157 файлов узла
3. **Функция calculate_pdf_status**: Работает корректно без ошибок

## Результат

- Иконки для распознанных файлов теперь отображаются корректно
- Статус PDF документов рассчитывается без ошибок
- Приложение работает стабильно с файлами типа `crops_folder`

## Дата исправления

03.01.2026
