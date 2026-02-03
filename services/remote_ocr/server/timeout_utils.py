"""Утилиты для расчёта динамического таймаута OCR задач."""

from __future__ import annotations

import json
import logging
from typing import Union

from .settings import settings

logger = logging.getLogger(__name__)


def count_blocks_from_data(blocks_data: Union[list, dict]) -> int:
    """Подсчитать количество блоков из данных.

    Args:
        blocks_data: Данные блоков в формате списка или document-структуры

    Returns:
        Количество блоков
    """
    if isinstance(blocks_data, list):
        return len(blocks_data)
    elif isinstance(blocks_data, dict) and "pages" in blocks_data:
        return sum(len(p.get("blocks", [])) for p in blocks_data.get("pages", []))
    return 0


def calculate_dynamic_timeout(block_count: int) -> tuple[int, int]:
    """Рассчитать динамический таймаут на основе количества блоков.

    Формула: base + (block_count * seconds_per_block)
    Результат ограничен min_task_timeout и max_task_timeout.

    Args:
        block_count: Количество блоков в документе

    Returns:
        Tuple (soft_timeout, hard_timeout) в секундах
    """
    soft_timeout = settings.dynamic_timeout_base + (
        block_count * settings.seconds_per_block
    )
    soft_timeout = max(
        settings.min_task_timeout, min(soft_timeout, settings.max_task_timeout)
    )

    # Hard timeout = soft + 10 минут запаса
    hard_timeout = soft_timeout + 600

    logger.info(
        f"Динамический таймаут: soft={soft_timeout}s, hard={hard_timeout}s "
        f"для {block_count} блоков "
        f"(base={settings.dynamic_timeout_base}, per_block={settings.seconds_per_block})"
    )

    return soft_timeout, hard_timeout


def parse_blocks_json(content: Union[str, bytes]) -> Union[list, dict]:
    """Распарсить JSON с блоками.

    Args:
        content: JSON строка или bytes

    Returns:
        Распарсенные данные блоков
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    return json.loads(content)
