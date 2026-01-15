"""Утилиты для работы с блоками."""
from typing import Dict, List

from rd_core.models.armor_id import is_armor_id, uuid_to_armor_id


def get_block_armor_id(block_id: str) -> str:
    """
    Получить armor ID блока.

    Новые блоки уже имеют ID в формате XXXX-XXXX-XXX.
    Для legacy UUID блоков - конвертируем в armor формат.
    """
    if is_armor_id(block_id):
        return block_id
    return uuid_to_armor_id(block_id)


def collect_block_groups(pages: List) -> Dict[str, List]:
    """Собрать блоки по группам."""
    groups: Dict[str, List] = {}
    for page in pages:
        for block in page.blocks:
            group_id = getattr(block, "group_id", None)
            if group_id:
                if group_id not in groups:
                    groups[group_id] = []
                groups[group_id].append(block)
    return groups
