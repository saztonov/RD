"""
Генерация Markdown-отчётов
Сбор результатов OCR в один MD-файл по каждой категории
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Union
from PIL import Image
from app.models import Document

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


def generate_markdown_reports(base_output_dir: str) -> None:
    """
    Генерировать Markdown-отчёты для всех категорий
    
    Args:
        base_output_dir: базовая директория с подпапками категорий
    """
    try:
        base_path = Path(base_output_dir)
        
        if not base_path.exists():
            logger.error(f"Директория не найдена: {base_output_dir}")
            return
        
        # Проходим по всем подпапкам (категориям)
        category_dirs = [d for d in base_path.iterdir() if d.is_dir()]
        logger.info(f"Найдено категорий: {len(category_dirs)}")
        
        for category_dir in category_dirs:
            category_name = category_dir.name
            blocks_json_path = category_dir / "blocks.json"
            
            # Проверяем наличие blocks.json
            if not blocks_json_path.exists():
                logger.warning(f"blocks.json не найден в {category_dir}")
                continue
            
            # Загружаем blocks.json
            try:
                with open(blocks_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга JSON в {blocks_json_path}: {e}")
                continue
            
            blocks = data.get("blocks", [])
            
            if not blocks:
                logger.warning(f"Нет блоков в категории '{category_name}'")
                continue
            
            # Сортируем блоки по page_index, затем по id
            blocks_sorted = sorted(blocks, key=lambda b: (b.get("page_index", 0), b.get("id", "")))
            
            # Создаём summary.md
            summary_path = category_dir / "summary.md"
            
            with open(summary_path, 'w', encoding='utf-8') as f:
                # Заголовок
                f.write(f"# {category_name}\n\n")
                f.write(f"**Category:** {data.get('category', category_name)}\n")
                f.write(f"**Source PDF:** {data.get('original_pdf', 'Unknown')}\n")
                f.write(f"**Total Blocks:** {len(blocks_sorted)}\n\n")
                
                # Блоки последовательно без разделителей страниц
                for block in blocks_sorted:
                    block_type = block.get("block_type", "unknown")
                    ocr_text = block.get("ocr_text", "")
                    
                    # OCR текст без заголовков блоков
                    if ocr_text:
                        if block_type == "table" and _is_markdown_table(ocr_text):
                            f.write(ocr_text)
                            f.write("\n\n")
                        else:
                            escaped_text = _escape_markdown(ocr_text)
                            f.write(escaped_text)
                            f.write("\n\n")
            
            logger.info(f"Генерирован отчёт для '{category_name}': {summary_path} ({len(blocks_sorted)} блоков)")
        
        logger.info(f"Генерация Markdown-отчётов завершена")
    
    except Exception as e:
        logger.error(f"Ошибка при генерации Markdown-отчётов: {e}", exc_info=True)
        raise


class MarkdownReporter:
    """Legacy класс для совместимости с GUI (работа с Document)"""
    
    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: директория для сохранения MD-отчётов
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_reports(self, document: Document) -> None:
        """
        Генерировать Markdown-отчёты для Document
        Блоки выводятся последовательно без разделения по страницам
        
        Args:
            document: экземпляр Document
        """
        try:
            # Группируем блоки по категориям
            blocks_by_category = {}
            
            for page in document.pages:
                for block in page.blocks:
                    category = block.category or "uncategorized"
                    if category not in blocks_by_category:
                        blocks_by_category[category] = []
                    blocks_by_category[category].append((page.page_number, block))
            
            # Создаём MD-файл для каждой категории
            for category, blocks_with_page in blocks_by_category.items():
                md_path = self.output_dir / f"{category}.md"
                
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {category}\n\n")
                    f.write(f"**Source PDF:** {document.pdf_path}\n")
                    f.write(f"**Total Blocks:** {len(blocks_with_page)}\n\n")
                    
                    # Сортируем по странице и вертикальной позиции
                    blocks_sorted = sorted(blocks_with_page, key=lambda x: (x[0], x[1].coords_px[1]))
                    
                    for page_num, block in blocks_sorted:
                        if block.ocr_text:
                            if block.block_type.value == "table" and _is_markdown_table(block.ocr_text):
                                f.write(block.ocr_text)
                                f.write("\n\n")
                            else:
                                escaped_text = _escape_markdown(block.ocr_text)
                                f.write(escaped_text)
                                f.write("\n\n")
                
                logger.info(f"Генерирован отчёт для '{category}': {md_path} ({len(blocks_with_page)} блоков)")
            
            logger.info(f"Генерация MD-отчётов завершена: {len(blocks_by_category)} категорий")
            
            # Общий отчет
            all_blocks = []
            for blocks_with_page in blocks_by_category.values():
                all_blocks.extend(blocks_with_page)
            
            if all_blocks:
                combined_path = self.output_dir / "combined_full_report.md"
                with open(combined_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Полный отчет\n\n")
                    f.write(f"**Source PDF:** {document.pdf_path}\n")
                    f.write(f"**Total Blocks:** {len(all_blocks)}\n\n")
                    
                    # Сортируем по странице и вертикальной позиции
                    all_blocks_sorted = sorted(all_blocks, key=lambda x: (x[0], x[1].coords_px[1]))
                    
                    for page_num, block in all_blocks_sorted:
                        if block.ocr_text:
                            if block.block_type.value == "table" and _is_markdown_table(block.ocr_text):
                                f.write(block.ocr_text)
                            else:
                                f.write(block.ocr_text)
                            f.write("\n\n")
                
                logger.info(f"Сгенерирован общий отчет: {combined_path}")

        except Exception as e:
            logger.error(f"Ошибка генерации отчётов: {e}")
            raise

