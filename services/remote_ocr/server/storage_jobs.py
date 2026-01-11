"""CRUD операции для задач OCR"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, List, Optional

from .queue_checker import _get_redis_client
from .storage_client import get_client
from .storage_models import Job, JobFile, JobSettings

logger = logging.getLogger(__name__)

# Redis кеш для list_jobs() - TTL 5 секунд
JOBS_CACHE_TTL = 5
JOBS_CACHE_PREFIX = "jobs:list:"

# Rate limiting для update_job_status
PROGRESS_UPDATE_INTERVAL = 3.0  # секунд
PROGRESS_UPDATE_THRESHOLD = 0.05  # 5%
LAST_UPDATE_KEY = "job:{job_id}:last_update"

# Redis кеш для is_job_paused
PAUSED_CACHE_KEY = "job:{job_id}:paused"
PAUSED_CACHE_TTL = 60  # секунд

# Метрики DB calls
DB_CALLS_KEY = "job:{job_id}:db_calls"

# Финальные статусы (всегда писать в БД)
FINAL_STATUSES = {"done", "error", "paused"}


def _get_jobs_cache_key(document_id: Optional[str]) -> str:
    """Формирует ключ кеша для list_jobs"""
    if document_id:
        return f"{JOBS_CACHE_PREFIX}doc:{document_id}"
    return f"{JOBS_CACHE_PREFIX}all"


def _invalidate_jobs_cache() -> None:
    """Инвалидирует весь кеш list_jobs"""
    try:
        client = _get_redis_client()
        keys = client.keys(f"{JOBS_CACHE_PREFIX}*")
        if keys:
            client.delete(*keys)
            logger.debug(f"Invalidated {len(keys)} jobs cache keys")
    except Exception as e:
        logger.warning(f"Failed to invalidate jobs cache: {e}")


def _increment_db_calls(job_id: str, count: int = 1) -> None:
    """Инкремент счётчика DB calls для job"""
    try:
        redis_client = _get_redis_client()
        redis_client.incrby(DB_CALLS_KEY.format(job_id=job_id), count)
    except Exception:
        pass


def log_db_metrics(job_id: str) -> None:
    """Логировать метрики DB calls и очистить счётчик"""
    try:
        redis_client = _get_redis_client()
        key = DB_CALLS_KEY.format(job_id=job_id)
        count = redis_client.get(key) or 0
        logger.info(f"Job {job_id}: {count} DB calls total")
        redis_client.delete(key)
        # Очистка связанных ключей
        redis_client.delete(LAST_UPDATE_KEY.format(job_id=job_id))
        redis_client.delete(PAUSED_CACHE_KEY.format(job_id=job_id))
    except Exception as e:
        logger.debug(f"Failed to log DB metrics: {e}")


def _should_update_progress(job_id: str, new_progress: float, status: str) -> bool:
    """Проверить, нужно ли обновлять прогресс в БД (rate limiting)"""
    # Финальные статусы - всегда пишем
    if status in FINAL_STATUSES:
        return True

    try:
        redis_client = _get_redis_client()
        key = LAST_UPDATE_KEY.format(job_id=job_id)
        cached = redis_client.get(key)

        if cached:
            data = json.loads(cached)
            last_time = data.get("time", 0)
            last_progress = data.get("progress", 0)

            time_delta = time.time() - last_time
            progress_delta = abs(new_progress - last_progress)

            # Пропустить если прошло мало времени И дельта мала
            if time_delta < PROGRESS_UPDATE_INTERVAL and progress_delta < PROGRESS_UPDATE_THRESHOLD:
                return False

        return True
    except Exception:
        return True  # При ошибке - писать


def _update_progress_cache(job_id: str, progress: float) -> None:
    """Обновить кеш последнего обновления прогресса"""
    try:
        redis_client = _get_redis_client()
        key = LAST_UPDATE_KEY.format(job_id=job_id)
        data = json.dumps({"time": time.time(), "progress": progress})
        redis_client.setex(key, 300, data)  # TTL 5 минут
    except Exception:
        pass


def create_job(
    client_id: str,
    document_id: str,
    document_name: str,
    task_name: str,
    engine: str,
    r2_prefix: str,
    status: str = "queued",
    node_id: Optional[str] = None,
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
        node_id=node_id,
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
        "r2_prefix": job.r2_prefix,
    }
    if node_id:
        insert_data["node_id"] = node_id

    client.table("jobs").insert(insert_data).execute()

    _invalidate_jobs_cache()
    return job


def get_job(
    job_id: str, with_files: bool = False, with_settings: bool = False
) -> Optional[Job]:
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


def list_jobs(document_id: Optional[str] = None) -> List[Job]:
    """Получить список задач (с Redis кешированием)"""
    cache_key = _get_jobs_cache_key(document_id)

    # Проверяем кеш
    try:
        redis_client = _get_redis_client()
        cached = redis_client.get(cache_key)
        if cached:
            jobs_data = json.loads(cached)
            return [_row_to_job(row) for row in jobs_data]
    except Exception as e:
        logger.debug(f"Cache miss or error: {e}")

    # Запрос к БД
    client = get_client()
    query = client.table("jobs").select("*")

    if document_id:
        query = query.eq("document_id", document_id)

    result = query.order("created_at", desc=True).execute()

    # Сохраняем в кеш
    try:
        redis_client = _get_redis_client()
        redis_client.setex(cache_key, JOBS_CACHE_TTL, json.dumps(result.data))
    except Exception as e:
        logger.debug(f"Failed to cache jobs: {e}")

    return [_row_to_job(row) for row in result.data]


def list_jobs_changed_since(since: str) -> List[Job]:
    """Получить задачи, изменённые после указанного времени (ISO timestamp)"""
    client = get_client()
    result = (
        client.table("jobs")
        .select("*")
        .gt("updated_at", since)
        .order("updated_at", desc=True)
        .execute()
    )
    return [_row_to_job(row) for row in result.data]


def update_job_status(
    job_id: str,
    status: str,
    progress: Optional[float] = None,
    error_message: Optional[str] = None,
    r2_prefix: Optional[str] = None,
    status_message: Optional[str] = None,
    force: bool = False,
) -> None:
    """Обновить статус задачи (с rate limiting для progress)"""
    # Rate limiting: проверить нужно ли писать
    if not force and progress is not None:
        if not _should_update_progress(job_id, progress, status):
            return  # Пропустить обновление

    now = datetime.utcnow().isoformat()

    updates: dict[str, Any] = {"status": status, "updated_at": now}

    if progress is not None:
        updates["progress"] = progress
    if error_message is not None:
        updates["error_message"] = error_message
    if r2_prefix is not None:
        updates["r2_prefix"] = r2_prefix
    if status_message is not None:
        updates["status_message"] = status_message

    client = get_client()
    client.table("jobs").update(updates).eq("id", job_id).execute()
    _increment_db_calls(job_id)
    _invalidate_jobs_cache()

    # Обновить кеш прогресса
    if progress is not None:
        _update_progress_cache(job_id, progress)


def update_job_engine(job_id: str, engine: str) -> None:
    """Обновить engine задачи и перевести в queued"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    client.table("jobs").update(
        {"engine": engine, "status": "queued", "updated_at": now}
    ).eq("id", job_id).execute()


def update_job_task_name(job_id: str, task_name: str) -> bool:
    """Обновить название задачи"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    result = (
        client.table("jobs")
        .update({"task_name": task_name, "updated_at": now})
        .eq("id", job_id)
        .execute()
    )
    return len(result.data) > 0


def delete_job(job_id: str) -> bool:
    """Удалить задачу из БД (каскадно удалит files и settings)"""
    client = get_client()
    result = client.table("jobs").delete().eq("id", job_id).execute()
    _invalidate_jobs_cache()
    return len(result.data) > 0


def reset_job_for_restart(job_id: str) -> bool:
    """Сбросить задачу для повторного запуска"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    result = (
        client.table("jobs")
        .update(
            {
                "status": "queued",
                "progress": 0,
                "error_message": None,
                "updated_at": now,
            }
        )
        .eq("id", job_id)
        .execute()
    )
    _invalidate_jobs_cache()
    return len(result.data) > 0


def pause_job(job_id: str) -> bool:
    """Поставить задачу на паузу"""
    now = datetime.utcnow().isoformat()
    client = get_client()

    result = (
        client.table("jobs")
        .update({"status": "paused", "updated_at": now})
        .eq("id", job_id)
        .eq("status", "queued")
        .execute()
    )

    if result.data:
        _invalidate_jobs_cache()
        _set_paused_cache(job_id, True)
        return True

    result = (
        client.table("jobs")
        .update({"status": "paused", "updated_at": now})
        .eq("id", job_id)
        .eq("status", "processing")
        .execute()
    )

    if result.data:
        _invalidate_jobs_cache()
        _set_paused_cache(job_id, True)
    return len(result.data) > 0


def resume_job(job_id: str) -> bool:
    """Возобновить задачу"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    result = (
        client.table("jobs")
        .update({"status": "queued", "updated_at": now})
        .eq("id", job_id)
        .eq("status", "paused")
        .execute()
    )
    if result.data:
        _invalidate_jobs_cache()
        _set_paused_cache(job_id, False)
    return len(result.data) > 0


def _set_paused_cache(job_id: str, paused: bool) -> None:
    """Установить кеш статуса паузы"""
    try:
        redis_client = _get_redis_client()
        key = PAUSED_CACHE_KEY.format(job_id=job_id)
        if paused:
            redis_client.setex(key, PAUSED_CACHE_TTL, "1")
        else:
            redis_client.delete(key)
    except Exception:
        pass


def is_job_paused(job_id: str) -> bool:
    """Проверить, поставлена ли задача на паузу (с Redis кешем)"""
    # Сначала проверяем Redis кеш
    try:
        redis_client = _get_redis_client()
        key = PAUSED_CACHE_KEY.format(job_id=job_id)
        cached = redis_client.get(key)
        if cached is not None:
            return cached == "1"
    except Exception:
        pass

    # Cache miss - запрос к БД
    job = get_job(job_id)
    paused = job.status == "paused" if job else False
    _increment_db_calls(job_id)

    # Сохранить в кеш
    _set_paused_cache(job_id, paused)

    return paused


def update_job_started(job_id: str) -> None:
    """Установить время начала обработки задачи"""
    now = datetime.utcnow().isoformat()
    client = get_client()
    client.table("jobs").update({
        "started_at": now,
        "status": "processing",
        "updated_at": now,
    }).eq("id", job_id).execute()
    _increment_db_calls(job_id)
    _invalidate_jobs_cache()


def update_job_completed(
    job_id: str,
    block_stats: Optional[dict] = None,
    error_message: Optional[str] = None,
) -> None:
    """Установить время завершения и статистику задачи"""
    now = datetime.utcnow().isoformat()

    status = "error" if error_message else "done"
    updates: dict[str, Any] = {
        "completed_at": now,
        "status": status,
        "progress": 1.0 if status == "done" else None,
        "updated_at": now,
    }

    if block_stats:
        updates["block_stats"] = json.dumps(block_stats) if isinstance(block_stats, dict) else block_stats
    if error_message:
        updates["error_message"] = error_message

    # Удаляем None значения
    updates = {k: v for k, v in updates.items() if v is not None}

    client = get_client()
    client.table("jobs").update(updates).eq("id", job_id).execute()
    _increment_db_calls(job_id)
    _invalidate_jobs_cache()


def _row_to_job(row: dict) -> Job:
    return Job(
        id=row["id"],
        client_id=row.get("client_id", ""),
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
        node_id=row.get("node_id"),
        status_message=row.get("status_message"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        block_stats=row.get("block_stats"),
    )
