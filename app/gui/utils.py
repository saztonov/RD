"""Общие утилиты GUI"""

import re
from datetime import datetime, timedelta, timezone


def transliterate_to_latin(text: str) -> str:
    """
    Транслитерация русского текста в латиницу + очистка для URL/путей
    
    Args:
        text: исходный текст (может содержать кириллицу, пробелы, спецсимволы)
    
    Returns:
        Очищенный текст (латиница, подчеркивания, без спецсимволов)
    """
    cyrillic_to_latin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'C', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }
    
    result = []
    for char in text:
        if char in cyrillic_to_latin:
            result.append(cyrillic_to_latin[char])
        else:
            result.append(char)
    
    transliterated = ''.join(result)
    transliterated = transliterated.replace(' ', '_')
    transliterated = re.sub(r'[^a-zA-Z0-9_\-]', '', transliterated)
    transliterated = re.sub(r'_{2,}', '_', transliterated)
    transliterated = transliterated.strip('_')
    
    return transliterated


def format_datetime_utc3(dt_str: str) -> str:
    """Конвертировать UTC время в UTC+3 (МСК)"""
    try:
        if dt_str.endswith('Z'):
            dt_utc = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        elif '+' not in dt_str and 'T' in dt_str:
            dt_utc = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
        else:
            dt_utc = datetime.fromisoformat(dt_str)
        
        utc3 = timezone(timedelta(hours=3))
        dt_local = dt_utc.astimezone(utc3)
        
        return dt_local.strftime("%H:%M %d.%m.%Y")
    except:
        return dt_str

