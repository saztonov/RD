"""Supabase-хранилище для задач OCR"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Any

from supabase import create_client, Client

from .settings import settings


@dataclass
class Job:
    id: str
    client_id: str
    document_id: str
    document_name: str
    task_name: str
    status: str  # draft|queued|processing|done|error|paused
    progress: float
    created_at: str
    updated_at: str
    error_message: Optional[str]
    job_dir: str
    result_path: Optional[str]
    engine: str = ""
    r2_prefix: Optional[str] = None


_supabase: Optional[Client] = None


def _get_client() -> Client:
    """Получить Supabase клиент (singleton)"""
    global _supabase
    if _supabase is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("SUPABASE_URL и SUPABASE_KEY должны быть заданы")
        _supabase = create_client(settings.supabase_url, settings.supabase_key)
    return _supabase


def init_db() -> None:
    """Инициализировать подключение к Supabase (проверка соединения)"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        client = _get_client()
        # Проверяем соединение простым запросом
        client.table("jobs").select("id").limit(1).execute()
        logger.info("✅ Supabase: подключение установлено")
    except Exception as e:
        logger.error(f"❌ Supabase: ошибка подключения: {e}")
        raise


def create_job(
    client_id: str,
    document_id: str,
    document_name: str,
    task_name: str,
    engine: str,
    job_dir: str,
    status: str = "queued"
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
        job_dir=job_dir,
        result_path=None,
        engine=engine,
        r2_prefix=None
    )
    
    client = _get_client()
    client.table("jobs").insert({
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
        "job_dir": job.job_dir,
        "result_path": job.result_path,
        "engine": job.engine,
        "r2_prefix": job.r2_prefix
    }).execute()
    
    return job


def get_job(job_id: str) -> Optional[Job]:
    """Получить задачу по ID"""
    client = _get_client()
    result = client.table("jobs").select("*").eq("id", job_id).execute()
    
    if not result.data:
        return None
    return _row_to_job(result.data[0])


def list_jobs(client_id: Optional[str] = None, document_id: Optional[str] = None) -> List[Job]:
    """Получить список задач. Если client_id не указан - возвращает все задачи."""
    client = _get_client()
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
    result_path: Optional[str] = None,
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
    if result_path is not None:
        updates["result_path"] = result_path
    if r2_prefix is not None:
        updates["r2_prefix"] = r2_prefix
    
    client = _get_client()
    client.table("jobs").update(updates).eq("id", job_id).execute()


def count_processing_jobs() -> int:
    """Подсчитать количество задач в статусе processing"""
    client = _get_client()
    result = client.table("jobs").select("id", count="exact").eq("status", "processing").execute()
    return result.count or 0


def claim_next_job(max_concurrent: int = 2) -> Optional[Job]:
    """Взять следующую задачу в очереди (атомарно переключить в processing)
    
    Args:
        max_concurrent: максимум параллельных задач (по умолчанию 2)
    """
    client = _get_client()
    
    # Проверяем лимит параллельных задач
    processing_count = count_processing_jobs()
    if processing_count >= max_concurrent:
        return None
    
    # Находим первую queued задачу
    result = client.table("jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
    
    if not result.data:
        return None
    
    job_id = result.data[0]["id"]
    now = datetime.utcnow().isoformat()
    
    # Атомарно помечаем как processing (с условием что status = queued)
    update_result = client.table("jobs").update({
        "status": "processing",
        "updated_at": now
    }).eq("id", job_id).eq("status", "queued").execute()
    
    # Перечитываем
    if update_result.data:
        return _row_to_job(update_result.data[0])
    
    # Если update не прошёл (status уже изменился), возвращаем None
    return None


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
        job_dir=row["job_dir"],
        result_path=row.get("result_path"),
        engine=row.get("engine", ""),
        r2_prefix=row.get("r2_prefix")
    )


def delete_job(job_id: str) -> bool:
    """Удалить задачу из БД"""
    client = _get_client()
    result = client.table("jobs").delete().eq("id", job_id).execute()
    return len(result.data) > 0


def reset_job_for_restart(job_id: str) -> bool:
    """Сбросить задачу для повторного запуска"""
    now = datetime.utcnow().isoformat()
    client = _get_client()
    result = client.table("jobs").update({
        "status": "queued",
        "progress": 0,
        "error_message": None,
        "result_path": None,
        "r2_prefix": None,
        "updated_at": now
    }).eq("id", job_id).execute()
    return len(result.data) > 0


def recover_stuck_jobs() -> int:
    """
    При старте воркера: ставим ВСЕ активные задачи (queued + processing) на паузу.
    Это предотвращает одновременный запуск всех задач после рестарта.
    
    Returns:
        Количество задач поставленных на паузу
    """
    import logging
    logger = logging.getLogger(__name__)
    
    now = datetime.utcnow().isoformat()
    client = _get_client()
    
    # Ставим на паузу queued
    result1 = client.table("jobs").update({
        "status": "paused",
        "updated_at": now
    }).eq("status", "queued").execute()
    
    # Ставим на паузу processing
    result2 = client.table("jobs").update({
        "status": "paused",
        "updated_at": now
    }).eq("status", "processing").execute()
    
    count = len(result1.data) + len(result2.data)
    if count > 0:
        logger.warning(f"⏸️ При старте: {count} задач поставлено на паузу (queued/processing -> paused)")
    return count


def pause_job(job_id: str) -> bool:
    """Поставить задачу на паузу (queued/processing -> paused)"""
    now = datetime.utcnow().isoformat()
    client = _get_client()
    
    # Сначала пробуем с queued
    result = client.table("jobs").update({
        "status": "paused",
        "updated_at": now
    }).eq("id", job_id).eq("status", "queued").execute()
    
    if result.data:
        return True
    
    # Потом с processing
    result = client.table("jobs").update({
        "status": "paused",
        "updated_at": now
    }).eq("id", job_id).eq("status", "processing").execute()
    
    return len(result.data) > 0


def resume_job(job_id: str) -> bool:
    """Возобновить задачу (paused -> queued)"""
    now = datetime.utcnow().isoformat()
    client = _get_client()
    result = client.table("jobs").update({
        "status": "queued",
        "updated_at": now
    }).eq("id", job_id).eq("status", "paused").execute()
    return len(result.data) > 0


def is_job_paused(job_id: str) -> bool:
    """Проверить, поставлена ли задача на паузу"""
    job = get_job(job_id)
    return job.status == "paused" if job else False


def job_to_dict(job: Job) -> dict:
    """Конвертировать Job в dict для JSON ответа"""
    return {
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
        "job_dir": job.job_dir,
        "result_path": job.result_path,
        "engine": job.engine,
        "r2_prefix": job.r2_prefix
    }


# --- Вспомогательные функции для main.py ---

def update_job_engine(job_id: str, engine: str) -> None:
    """Обновить engine задачи"""
    now = datetime.utcnow().isoformat()
    client = _get_client()
    client.table("jobs").update({
        "engine": engine,
        "status": "queued",
        "updated_at": now
    }).eq("id", job_id).execute()
