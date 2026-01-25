"""Типы данных для сверки файлов."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DiscrepancyType(str, Enum):
    """Тип несоответствия"""
    ORPHAN_R2 = "orphan_r2"  # Файл есть в R2, но нет в Supabase
    ORPHAN_DB = "orphan_db"  # Запись есть в Supabase, но нет в R2
    SIZE_MISMATCH = "size_mismatch"  # Размер файла не совпадает


@dataclass
class FileDiscrepancy:
    """Информация о несоответствии файла"""
    r2_key: str
    discrepancy_type: DiscrepancyType
    r2_size: Optional[int] = None
    db_size: Optional[int] = None
    db_file_id: Optional[str] = None
    file_type: Optional[str] = None
    file_name: Optional[str] = None
