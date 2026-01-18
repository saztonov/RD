"""Matching block ID для OCR результатов (ARMOR коды)"""
from __future__ import annotations

import re
from typing import Optional

# Новый формат: BLOCK: XXXX-XXXX-XXX (armor код)
# OCR может искажать: пропускать/добавлять символы и дефисы
# Ловим любые последовательности 8-14 символов (алфавит + цифры + дефисы)
ARMOR_BLOCK_MARKER_RE = re.compile(
    r"BLOCK:\s*([A-Z0-9]{2,5}[-\s]*[A-Z0-9]{2,5}[-\s]*[A-Z0-9]{2,5})", re.IGNORECASE
)


def match_armor_code(
    armor_code: str,
    expected_ids: list[str],
    expected_set: set[str],
) -> tuple[Optional[str], float]:
    """
    Сопоставить armor код (XXXX-XXXX-XXX) с ожидаемыми UUID.
    Использует ArmorID для восстановления и декодирования.
    """
    from rd_domain.ids import match_armor_to_uuid

    matched_uuid, score = match_armor_to_uuid(armor_code, expected_ids)
    return matched_uuid, score
