"""CRUD операции для задач OCR"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Any

from .storage_client import get_client
from .storage_models import Job, JobFile, JobSettings

logger = logging.getLogger(__name__)


def create_job(
    client_id: str,
    document_id: str,
    document_name: str,
    task_name: str,
    engine: str,
    r2_prefix: str,
    status: str = "queued",
    node_id: Optional[str] = None
) -> Job:
    """Создать новую задачу"""
    job_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    job = Job(
        id=job_id,
        client_id=client_id,
        document_id=document_id,
        document_name=document_name,
        task_name=task_name,
        status=status,
        progress=0.0,
        created_at=now,
        updated_at=now,
        error_message=None,
        engine=engine,
        r2_prefix=r2_prefix,
        node_id=node_id
    )
    
    client = get_client()
    insert_data = {
        "id": job.id,
        "client_id": job.client_id,
        "document_id": job.document_id,
        "document_name": job.document_name,
        "task_name": job.task_name,
        "status": job.status,
        "progress": job.progress,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "error_message": job.error_message,
        "engine": job.engine,
        "r2_prefix": job.r2_prefix
    }
    if node_id:
        insert_data["node_id"] = node_id
    
    client.table("jobs").insert(insert_data).execute()
    
    return job


def get_job(job_id: str, with_files: bool = False, with_settings: bool = False) -> Optional[Job]:
    """Получить задачу по ID"""
    from .storage_files import get_job_files
    from .storage_settings import get_job_settings
    
    client = get_client()
    result = client.table("jobs").select("*").eq("id", job_id).execute()
    
    if not result.data:
        return None
    
    job = _row_to_job(result.data[0])
    
    if with_files:
        job.files = get_job_files(job_id)
    if with_settings:
        job.settings = get_job_settings(job_id)
    
    return job


def list_jobs(client_id: Optional[str] = None, document_id: Optional[str] = None) -> List[Job]:
    """Получить список задач"""
    client = get_client()
    query = client.table("jobs").select("*")
    
    if client_id and document_id:
        query = query.eq("client_id", client_id).eq("document_id", document_id)
    elif client_id:
        query = query.eq("client_id", client_id)
    elif document_id:
        query = query.eq("document_id", document_id)
    
    result = query.order("created_at", desc=True).execute()
    return [_row_to_job(row) for row in result.data]


def update_job_status(
    job_id: str,
    status: str,
    progress: Optional[float] = None,
    error_message: Optional[str] = None,
    r2_prefix: Optional[str] = None
) -> None:
    """Обновить статус задачи"""
    now = datetime.utcnow().isoformat()
    
    updates: dict[str, Any] = {
        "status": status,
        "updated_at": now
    }
    
    if progress is not None:
        updates["progress"] = progress
    if error_message is not None:
        updates["error_message"] = error_message
    if r2_prefix is not None:
        updates["r2_prefix"] = r2_prefix
    
    client = get_client()
    client.table("jobs").update(updates).eq("id", job_id).execute()


def update_job_engine(job_id: str, engine: str) -> None:
    """Обновить engine задачи и перевести в queued"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    client.table("jobs").update({
        "engine": engine,
        "status": "queued",
        "updated_at": now
    }).eq("id", job_id).execute()


def update_job_task_name(job_id: str, task_name: str) -> bool:
    """Обновить название задачи"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    result = client.table("jobs").update({
        "task_name": task_name,
        "updated_at": now
    }).eq("id", job_id).execute()
    return len(result.data) > 0


def count_processing_jobs() -> int:
    """Подсчитать количество задач в статусе processing"""
    client = get_client()
    result = client.table("jobs").select("id", count="exact").eq("status", "processing").execute()
    return result.count or 0


def claim_next_job(max_concurrent: int = 2) -> Optional[Job]:
    """Взять следующую задачу в очереди (атомарно переключить в processing)"""
    from .storage_files import get_job_files
    from .storage_settings import get_job_settings
    
    client = get_client()
    
    processing_count = count_processing_jobs()
    if processing_count >= max_concurrent:
        return None
    
    result = client.table("jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
    
    if not result.data:
        return None
    
    job_id = result.data[0]["id"]
    now = datetime.utcnow().isoformat()
    
    update_result = client.table("jobs").update({
        "status": "processing",
        "updated_at": now
    }).eq("id", job_id).eq("status", "queued").execute()
    
    if update_result.data:
        job = _row_to_job(update_result.data[0])
        # Загружаем файлы и настройки для обработки
        job.files = get_job_files(job_id)
        job.settings = get_job_settings(job_id)
        return job
    
    return None


def delete_job(job_id: str) -> bool:
    """Удалить задачу из БД (каскадно удалит files и settings)"""
    client = get_client()
    result = client.table("jobs").delete().eq("id", job_id).execute()
    return len(result.data) > 0


def reset_job_for_restart(job_id: str) -> bool:
    """Сбросить задачу для повторного запуска"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    result = client.table("jobs").update({
        "status": "queued",
        "progress": 0,
        "error_message": None,
        "updated_at": now
    }).eq("id", job_id).execute()
    return len(result.data) > 0


def recover_stuck_jobs() -> int:
    """При старте воркера: ставим ВСЕ активные задачи на паузу"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    
    result1 = client.table("jobs").update({
        "status": "paused",
        "updated_at": now
    }).eq("status", "queued").execute()
    
    result2 = client.table("jobs").update({
        "status": "paused",
        "updated_at": now
    }).eq("status", "processing").execute()
    
    count = len(result1.data) + len(result2.data)
    if count > 0:
        logger.warning(f"⏸️ При старте: {count} задач поставлено на паузу")
    return count


def pause_job(job_id: str) -> bool:
    """Поставить задачу на паузу"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    
    result = client.table("jobs").update({
        "status": "paused",
        "updated_at": now
    }).eq("id", job_id).eq("status", "queued").execute()
    
    if result.data:
        return True
    
    result = client.table("jobs").update({
        "status": "paused",
        "updated_at": now
    }).eq("id", job_id).eq("status", "processing").execute()
    
    return len(result.data) > 0


def resume_job(job_id: str) -> bool:
    """Возобновить задачу"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    result = client.table("jobs").update({
        "status": "queued",
        "updated_at": now
    }).eq("id", job_id).eq("status", "paused").execute()
    return len(result.data) > 0


def is_job_paused(job_id: str) -> bool:
    """Проверить, поставлена ли задача на паузу"""
    job = get_job(job_id)
    return job.status == "paused" if job else False


def _row_to_job(row: dict) -> Job:
    return Job(
        id=row["id"],
        client_id=row["client_id"],
        document_id=row["document_id"],
        document_name=row["document_name"],
        task_name=row.get("task_name", ""),
        status=row["status"],
        progress=row["progress"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_message=row.get("error_message"),
        engine=row.get("engine", ""),
        r2_prefix=row.get("r2_prefix", ""),
        node_id=row.get("node_id")
    )

