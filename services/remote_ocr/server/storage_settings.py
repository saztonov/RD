"""Операции с настройками задач OCR"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .storage_client import get_client
from .storage_models import JobSettings


def save_job_settings(
    job_id: str,
    text_model: str = "",
    table_model: str = "",
    image_model: str = ""
) -> JobSettings:
    """Сохранить/обновить настройки задачи"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    
    # Upsert: вставить или обновить
    client.table("job_settings").upsert({
        "job_id": job_id,
        "text_model": text_model,
        "table_model": table_model,
        "image_model": image_model,
        "updated_at": now
    }, on_conflict="job_id").execute()
    
    return JobSettings(
        job_id=job_id,
        text_model=text_model,
        table_model=table_model,
        image_model=image_model
    )


def get_job_settings(job_id: str) -> Optional[JobSettings]:
    """Получить настройки задачи"""
    client = get_client()
    result = client.table("job_settings").select("*").eq("job_id", job_id).execute()
    
    if not result.data:
        return None
    
    row = result.data[0]
    return JobSettings(
        job_id=row["job_id"],
        text_model=row.get("text_model", ""),
        table_model=row.get("table_model", ""),
        image_model=row.get("image_model", "")
    )

