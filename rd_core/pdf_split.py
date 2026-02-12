"""Утилита разделения PDF документов на части."""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class SplitPart:
    """Результат разделения одной части PDF."""

    part_index: int  # 0-based индекс части
    file_path: str  # Путь к файлу части
    page_range: Tuple[int, int]  # (start_page, end_page) inclusive, 0-based
    page_count: int  # Количество страниц в части
    file_size: int  # Размер файла в байтах


def calculate_page_ranges(
    total_pages: int, num_parts: int
) -> List[Tuple[int, int]]:
    """
    Вычислить диапазоны страниц для разделения.

    Неравномерное распределение: первые части получают +1 страницу.
    Пример: 10 страниц / 3 = [4, 3, 3] -> [(0,3), (4,6), (7,9)]

    Args:
        total_pages: Общее количество страниц
        num_parts: Количество частей

    Returns:
        Список кортежей (start_page, end_page) включительно, 0-based

    Raises:
        ValueError: если num_parts < 2 или > total_pages
    """
    if num_parts < 2:
        raise ValueError(
            f"Количество частей должно быть >= 2, получено: {num_parts}"
        )
    if num_parts > total_pages:
        raise ValueError(
            f"Количество частей ({num_parts}) больше количества страниц ({total_pages})"
        )

    base_size = total_pages // num_parts
    remainder = total_pages % num_parts

    ranges = []
    start = 0
    for i in range(num_parts):
        size = base_size + (1 if i < remainder else 0)
        end = start + size - 1
        ranges.append((start, end))
        start = end + 1

    return ranges


def split_pdf(
    input_path: str,
    output_dir: str,
    num_parts: int,
    name_template: str = "Часть {part}. {name}",
) -> Tuple[bool, List[SplitPart], str]:
    """
    Разделить PDF файл на N частей.

    Использует fitz.Document.insert_pdf() для постраничного копирования.

    Args:
        input_path: Путь к исходному PDF
        output_dir: Директория для сохранения частей
        num_parts: Количество частей
        name_template: Шаблон имени. {part} = номер (1-based), {name} = имя без расширения

    Returns:
        (success, parts, error_message)
    """
    input_file = Path(input_path)
    out_dir = Path(output_dir)

    if not input_file.exists():
        return False, [], f"Файл не найден: {input_path}"

    try:
        src_doc = fitz.open(str(input_file))
    except Exception as e:
        return False, [], f"Не удалось открыть PDF: {e}"

    try:
        total_pages = len(src_doc)
        if total_pages < 2:
            return False, [], "PDF содержит только 1 страницу"

        ranges = calculate_page_ranges(total_pages, num_parts)
        out_dir.mkdir(parents=True, exist_ok=True)

        original_stem = input_file.stem
        parts: List[SplitPart] = []

        for i, (start, end) in enumerate(ranges):
            part_name = name_template.format(
                part=i + 1, name=original_stem
            )
            if not part_name.lower().endswith(".pdf"):
                part_name += ".pdf"

            part_path = out_dir / part_name

            # Создаём новый документ и копируем страницы
            new_doc = fitz.open()
            new_doc.insert_pdf(src_doc, from_page=start, to_page=end)
            new_doc.save(str(part_path))
            new_doc.close()

            file_size = part_path.stat().st_size
            parts.append(
                SplitPart(
                    part_index=i,
                    file_path=str(part_path),
                    page_range=(start, end),
                    page_count=end - start + 1,
                    file_size=file_size,
                )
            )

            logger.info(
                f"Часть {i + 1}/{num_parts}: стр. {start + 1}-{end + 1} "
                f"({end - start + 1} стр., {file_size} байт)"
            )

        logger.info(
            f"PDF разделён на {num_parts} частей: {input_path}"
        )
        return True, parts, ""

    except Exception as e:
        logger.exception(f"Ошибка разделения PDF: {e}")
        return False, [], str(e)
    finally:
        src_doc.close()
