"""Операции с файлами задач OCR"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List

from .storage_client import get_client
from .storage_models import JobFile


def add_job_file(
    job_id: str,
    file_type: str,
    r2_key: str,
    file_name: str,
    file_size: int = 0
) -> JobFile:
    """Добавить запись о файле задачи"""
    file_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    client = get_client()
    client.table("job_files").insert({
        "id": file_id,
        "job_id": job_id,
        "file_type": file_type,
        "r2_key": r2_key,
        "file_name": file_name,
        "file_size": file_size,
        "created_at": now
    }).execute()
    
    return JobFile(
        id=file_id,
        job_id=job_id,
        file_type=file_type,
        r2_key=r2_key,
        file_name=file_name,
        file_size=file_size,
        created_at=now
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
    return JobFile(
        id=row["id"],
        job_id=row["job_id"],
        file_type=row["file_type"],
        r2_key=row["r2_key"],
        file_name=row["file_name"],
        file_size=row.get("file_size", 0),
        created_at=row["created_at"]
    )

