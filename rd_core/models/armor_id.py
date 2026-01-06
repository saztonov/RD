"""
ArmorID - OCR-устойчивый формат идентификаторов блоков.

ArmorID использует алфавит из 26 символов, устойчивых к ошибкам OCR,
и включает контрольную сумму для валидации.
"""
import secrets
from datetime import datetime, timedelta, timezone

# Московский часовой пояс (UTC+3)
_MSK_TZ = timezone(timedelta(hours=3))


def get_moscow_time_str() -> str:
    """Получить текущее московское время в формате 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now(_MSK_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ArmorID алфавит (26 OCR-устойчивых символов)
_ARMOR_ALPHABET = "34679ACDEFGHJKLMNPQRTUVWXY"
_ARMOR_CHAR_MAP = {c: i for i, c in enumerate(_ARMOR_ALPHABET)}


def _num_to_base26(num: int, length: int) -> str:
    """Конвертировать число в base26 строку фиксированной длины."""
    if num == 0:
        return _ARMOR_ALPHABET[0] * length
    result = []
    while num > 0:
        result.append(_ARMOR_ALPHABET[num % 26])
        num //= 26
    while len(result) < length:
        result.append(_ARMOR_ALPHABET[0])
    return "".join(reversed(result[-length:]))


def _calculate_checksum(payload: str) -> str:
    """Вычислить 3-символьную контрольную сумму."""
    v1, v2, v3 = 0, 0, 0
    for i, char in enumerate(payload):
        val = _ARMOR_CHAR_MAP.get(char, 0)
        v1 += val
        v2 += val * (i + 3)
        v3 += val * (i + 7) * (i + 1)
    return (
        _ARMOR_ALPHABET[v1 % 26] + _ARMOR_ALPHABET[v2 % 26] + _ARMOR_ALPHABET[v3 % 26]
    )


def generate_armor_id() -> str:
    """
    Генерировать уникальный ID блока в формате XXXX-XXXX-XXX.

    40 бит энтропии (8 символов payload) + 3 символа контрольной суммы.
    """
    # 40 бит = 5 байт
    random_bytes = secrets.token_bytes(5)
    num = int.from_bytes(random_bytes, "big")

    payload = _num_to_base26(num, 8)
    checksum = _calculate_checksum(payload)
    full_code = payload + checksum
    return f"{full_code[:4]}-{full_code[4:8]}-{full_code[8:]}"


def is_armor_id(block_id: str) -> bool:
    """Проверить, является ли ID armor форматом (XXXX-XXXX-XXX)."""
    clean = block_id.replace("-", "").upper()
    return len(clean) == 11 and all(c in _ARMOR_ALPHABET for c in clean)


def uuid_to_armor_id(uuid_str: str) -> str:
    """Конвертировать UUID в armor ID формат."""
    clean = uuid_str.replace("-", "").lower()
    hex_prefix = clean[:10]
    num = int(hex_prefix, 16)
    payload = _num_to_base26(num, 8)
    checksum = _calculate_checksum(payload)
    full_code = payload + checksum
    return f"{full_code[:4]}-{full_code[4:8]}-{full_code[8:]}"


def migrate_block_id(block_id: str) -> tuple[str, bool]:
    """
    Мигрировать ID блока в armor формат если нужно.

    Returns: (new_id, was_migrated)
    """
    if is_armor_id(block_id):
        return block_id, False
    # Legacy UUID -> armor
    return uuid_to_armor_id(block_id), True
