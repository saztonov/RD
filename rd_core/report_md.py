"""
Генерация Markdown-отчётов
"""

import json
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


def update_smart_index(json_response: Union[str, dict], image_filename: str, index_file: str = "index.md") -> None:
    """
    Принимает JSON-ответ от QWEN и добавляет его в Markdown-индекс.
    
    Args:
        json_response: Словарь (dict) или JSON-строка от LLM
        image_filename: Имя файла картинки (тайла), к которому относится описание
        index_file: Путь к файлу индекса
    """
    try:
        # 1. Проверка и парсинг входных данных
        if isinstance(json_response, str):
            # Чистим от возможных markdown-оберток ```json ... ```
            clean_json = json_response.replace("```json", "").replace("```", "").strip()
            try:
                data = json.loads(clean_json)
            except json.JSONDecodeError:
                logger.error(f"Невалидный JSON для файла {image_filename}")
                return
        else:
            data = json_response
        
        # 2. Извлечение данных (с защитой от отсутствующих полей)
        loc = data.get("location", {})
        grid_lines = loc.get("grid_lines", "Не определены")
        zone_name = loc.get("zone_name", "Общая зона")
        
        summary = data.get("content_summary", "Описание отсутствует")
        ocr_text = data.get("ocr_text", "").replace("\n", " ")  # Убираем лишние переносы
        
        # Обработка списка сущностей
        entities = data.get("key_entities", [])
        if isinstance(entities, list):
            entities_str = ", ".join(entities)
        else:
            entities_str = str(entities)
        
        # 3. Формирование Markdown-блока
        # Оборачиваем JSON в HTML-комментарий для машинной обработки
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        
        # Конвертируем путь в POSIX формат (прямые слэши) для кроссплатформенности
        image_filename_posix = Path(image_filename).as_posix()
        
        markdown_entry = f"""
## Файл: `{image_filename_posix}`

<!-- 
{json_str}
-->

- **Локация (Оси):** {grid_lines}
- **Зона:** {zone_name}
- **Ключевые элементы:** {entities_str}
- **Описание:** {summary}
- **OCR (Контент):** {ocr_text[:500]}... *(показано начало)*

{ocr_text}
---

"""
        
        # 4. Запись в файл (Режим 'a' - append, добавление в конец)
        index_path = Path(index_file)
        
        # Если файла нет, создадим заголовок
        if not index_path.exists():
            index_path.parent.mkdir(parents=True, exist_ok=True)
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(f"# Индекс проектной документации\n*Автоматически сгенерирован*\n\n")
        
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(markdown_entry)
        
        logger.info(f"Индекс обновлен: добавлен блок для {image_filename}")
        
    except Exception as e:
        logger.error(f"Ошибка записи в индекс для {image_filename}: {e}")


def _escape_markdown(text: str) -> str:
    """
    Экранировать спецсимволы для Markdown (кроме символов в таблицах)
    
    Args:
        text: исходный текст
    
    Returns:
        Экранированный текст
    """
    # Базовый набор спецсимволов для экранирования
    # Не экранируем * и # если они часть структуры таблицы
    escape_chars = {
        '\\': '\\\\',
        '`': '\\`',
        '[': '\\[',
        ']': '\\]',
    }
    
    result = text
    for char, escaped in escape_chars.items():
        result = result.replace(char, escaped)
    
    return result


def _is_markdown_table(text: str) -> bool:
    """
    Проверить, является ли текст Markdown-таблицей
    
    Args:
        text: текст для проверки
    
    Returns:
        True если это похоже на Markdown-таблицу
    """
    lines = text.strip().split('\n')
    if len(lines) < 2:
        return False
    
    # Проверяем наличие разделителя (строка с |---|---)
    for line in lines[1:]:
        if '|' in line and '-' in line:
            # Это похоже на таблицу
            return True
    
    return False

