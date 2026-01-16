"""Операции с файлами задач OCR"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .storage_client import get_client
from .storage_models import JobFile


def add_job_file(
    job_id: str,
    file_type: str,
    r2_key: str,
    file_name: str,
    file_size: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
) -> JobFile:
    """Добавить запись о файле задачи.

    Args:
        job_id: ID задачи
        file_type: Тип файла (pdf, blocks, annotation, result, result_md, ocr_html, crop)
        r2_key: Путь к файлу в R2
        file_name: Имя файла
        file_size: Размер файла в байтах
        metadata: Метаданные файла (для кропов: block_id, page_index, coords_norm, block_type)
    """
    file_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    row = {
        "id": file_id,
        "job_id": job_id,
        "file_type": file_type,
        "r2_key": r2_key,
        "file_name": file_name,
        "file_size": file_size,
        "created_at": now,
    }

    if metadata:
        row["metadata"] = json.dumps(metadata)

    client = get_client()
    client.table("job_files").insert(row).execute()

    return JobFile(
        id=file_id,
        job_id=job_id,
        file_type=file_type,
        r2_key=r2_key,
        file_name=file_name,
        file_size=file_size,
        created_at=now,
        metadata=metadata,
    )


def get_job_files(job_id: str, file_type: Optional[str] = None) -> List[JobFile]:
    """Получить файлы задачи"""
    client = get_client()
    query = client.table("job_files").select("*").eq("job_id", job_id)

    if file_type:
        query = query.eq("file_type", file_type)

    result = query.execute()
    return [_row_to_job_file(row) for row in result.data]


def get_job_file_by_type(job_id: str, file_type: str) -> Optional[JobFile]:
    """Получить конкретный файл задачи по типу"""
    files = get_job_files(job_id, file_type)
    return files[0] if files else None


def delete_job_files(job_id: str, file_types: Optional[List[str]] = None) -> int:
    """Удалить файлы задачи (из БД, не из R2)"""
    client = get_client()
    query = client.table("job_files").delete().eq("job_id", job_id)

    if file_types:
        query = query.in_("file_type", file_types)

    result = query.execute()
    return len(result.data)


def _row_to_job_file(row: dict) -> JobFile:
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = None

    return JobFile(
        id=row["id"],
        job_id=row["job_id"],
        file_type=row["file_type"],
        r2_key=row["r2_key"],
        file_name=row["file_name"],
        file_size=row.get("file_size", 0),
        created_at=row["created_at"],
        metadata=metadata,
    )
