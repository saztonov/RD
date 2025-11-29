"""
Генерация Markdown-отчётов
Сбор результатов OCR в один MD-файл по каждой категории
"""

import json
import logging
from pathlib import Path
from typing import Dict
from PIL import Image
from app.models import Document

logger = logging.getLogger(__name__)


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
                f.write("---\n\n")
                
                # Блоки
                for block in blocks_sorted:
                    block_id = block.get("id", "unknown")
                    page_index = block.get("page_index", 0)
                    block_type = block.get("block_type", "unknown")
                    ocr_text = block.get("ocr_text", "")
                    
                    # Заголовок блока
                    f.write(f"## Block {block_id} (Page {page_index}, Type: {block_type})\n\n")
                    
                    # OCR текст или заглушка
                    if ocr_text:
                        # Проверяем, является ли текст Markdown-таблицей
                        if block_type == "table" and _is_markdown_table(ocr_text):
                            # Таблица - пишем как есть
                            f.write(ocr_text)
                            f.write("\n\n")
                        else:
                            # Обычный текст - экранируем
                            escaped_text = _escape_markdown(ocr_text)
                            f.write(escaped_text)
                            f.write("\n\n")
                    else:
                        f.write("*Нет OCR-данных*\n\n")
                    
                    f.write("---\n\n")
            
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
                    blocks_by_category[category].append(block)
            
            # Создаём MD-файл для каждой категории
            for category, blocks in blocks_by_category.items():
                md_path = self.output_dir / f"{category}.md"
                
                with open(md_path, 'w', encoding='utf-8') as f:
                    # Заголовок
                    f.write(f"# {category}\n\n")
                    f.write(f"**Source PDF:** {document.pdf_path}\n")
                    f.write(f"**Total Blocks:** {len(blocks)}\n\n")
                    f.write("---\n\n")
                    
                    # Сортируем блоки по page_index
                    blocks_sorted = sorted(blocks, key=lambda b: (b.page_index, b.id))
                    
                    # Выводим блоки
                    for block in blocks_sorted:
                        f.write(f"## Block {block.id} (Page {block.page_index}, Type: {block.block_type.value})\n\n")
                        
                        if block.ocr_text:
                            # Проверяем тип блока для таблиц
                            if block.block_type.value == "table" and _is_markdown_table(block.ocr_text):
                                f.write(block.ocr_text)
                                f.write("\n\n")
                            else:
                                escaped_text = _escape_markdown(block.ocr_text)
                                f.write(escaped_text)
                                f.write("\n\n")
                        else:
                            f.write("*Нет OCR-данных*\n\n")
                        
                        f.write("---\n\n")
                
                logger.info(f"Генерирован отчёт для '{category}': {md_path} ({len(blocks)} блоков)")
            
            logger.info(f"Генерация MD-отчётов завершена: {len(blocks_by_category)} категорий")
        
        except Exception as e:
            logger.error(f"Ошибка генерации отчётов: {e}")
            raise

