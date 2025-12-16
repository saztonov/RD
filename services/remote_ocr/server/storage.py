"""SQLite-хранилище для задач OCR"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Any

from .settings import settings


@dataclass
class Job:
    id: str
    client_id: str
    document_id: str
    document_name: str
    task_name: str
    status: str  # queued|processing|done|error
    progress: float
    created_at: str
    updated_at: str
    error_message: Optional[str]
    job_dir: str
    result_path: Optional[str]
    engine: str = ""
    r2_prefix: Optional[str] = None


_db_lock = threading.Lock()
_db_path: Optional[str] = None


def _get_db_path() -> str:
    global _db_path
    if _db_path is None:
        os.makedirs(settings.data_dir, exist_ok=True)
        _db_path = os.path.join(settings.data_dir, "jobs.sqlite")
    return _db_path


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Инициализировать БД (создать таблицу если не существует)"""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    document_name TEXT NOT NULL,
                    task_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT,
                    job_dir TEXT NOT NULL,
                    result_path TEXT,
                    engine TEXT DEFAULT '',
                    r2_prefix TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_client_id ON jobs(client_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_document_id ON jobs(document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")
            conn.commit()
            
            # Миграция: добавляем r2_prefix если его нет
            try:
                cursor = conn.execute("PRAGMA table_info(jobs)")
                columns = [row[1] for row in cursor.fetchall()]
                if "r2_prefix" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN r2_prefix TEXT")
                    conn.commit()
                    import logging
                    logging.getLogger(__name__).info("✅ Миграция БД: добавлена колонка r2_prefix")
                if "task_name" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN task_name TEXT NOT NULL DEFAULT ''")
                    conn.commit()
                    import logging
                    logging.getLogger(__name__).info("✅ Миграция БД: добавлена колонка task_name")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"⚠️ Ошибка миграции БД: {e}")
        finally:
            conn.close()


def create_job(
    client_id: str,
    document_id: str,
    document_name: str,
    task_name: str,
    engine: str,
    job_dir: str
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
        status="queued",
        progress=0.0,
        created_at=now,
        updated_at=now,
        error_message=None,
        job_dir=job_dir,
        result_path=None,
        engine=engine,
        r2_prefix=None
    )
    
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute("""
                INSERT INTO jobs (id, client_id, document_id, document_name, task_name, status, progress,
                                  created_at, updated_at, error_message, job_dir, result_path, engine, r2_prefix)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (job.id, job.client_id, job.document_id, job.document_name, job.task_name, job.status,
                  job.progress, job.created_at, job.updated_at, job.error_message,
                  job.job_dir, job.result_path, job.engine, job.r2_prefix))
            conn.commit()
        finally:
            conn.close()
    
    return job


def get_job(job_id: str) -> Optional[Job]:
    """Получить задачу по ID"""
    with _db_lock:
        conn = _get_connection()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            return _row_to_job(row)
        finally:
            conn.close()


def list_jobs(client_id: Optional[str] = None, document_id: Optional[str] = None) -> List[Job]:
    """Получить список задач. Если client_id не указан - возвращает все задачи."""
    with _db_lock:
        conn = _get_connection()
        try:
            if client_id and document_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE client_id = ? AND document_id = ? ORDER BY created_at DESC",
                    (client_id, document_id)
                ).fetchall()
            elif client_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE client_id = ? ORDER BY created_at DESC",
                    (client_id,)
                ).fetchall()
            elif document_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE document_id = ? ORDER BY created_at DESC",
                    (document_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC"
                ).fetchall()
            return [_row_to_job(row) for row in rows]
        finally:
            conn.close()


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
    
    with _db_lock:
        conn = _get_connection()
        try:
            # Собираем SET-части запроса
            updates = ["status = ?", "updated_at = ?"]
            values: List[Any] = [status, now]
            
            if progress is not None:
                updates.append("progress = ?")
                values.append(progress)
            
            if error_message is not None:
                updates.append("error_message = ?")
                values.append(error_message)
            
            if result_path is not None:
                updates.append("result_path = ?")
                values.append(result_path)
            
            if r2_prefix is not None:
                updates.append("r2_prefix = ?")
                values.append(r2_prefix)
            
            values.append(job_id)
            
            conn.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                tuple(values)
            )
            conn.commit()
        finally:
            conn.close()


def claim_next_job() -> Optional[Job]:
    """Взять следующую задачу в очереди (атомарно переключить в processing)"""
    with _db_lock:
        conn = _get_connection()
        try:
            # Находим первую queued задачу
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            
            if row is None:
                return None
            
            job_id = row["id"]
            now = datetime.utcnow().isoformat()
            
            # Атомарно помечаем как processing
            conn.execute(
                "UPDATE jobs SET status = 'processing', updated_at = ? WHERE id = ? AND status = 'queued'",
                (now, job_id)
            )
            conn.commit()
            
            # Перечитываем
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row and row["status"] == "processing":
                return _row_to_job(row)
            return None
        finally:
            conn.close()


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        client_id=row["client_id"],
        document_id=row["document_id"],
        document_name=row["document_name"],
        task_name=row["task_name"] if "task_name" in row.keys() else "",
        status=row["status"],
        progress=row["progress"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_message=row["error_message"],
        job_dir=row["job_dir"],
        result_path=row["result_path"],
        engine=row["engine"] if "engine" in row.keys() else "",
        r2_prefix=row["r2_prefix"] if "r2_prefix" in row.keys() else None
    )


def delete_job(job_id: str) -> bool:
    """Удалить задачу из БД"""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def recover_stuck_jobs() -> int:
    """
    Восстановить застрявшие задачи: сбросить 'processing' обратно в 'queued'.
    Вызывается при старте воркера.
    
    Returns:
        Количество восстановленных задач
    """
    import logging
    logger = logging.getLogger(__name__)
    
    with _db_lock:
        conn = _get_connection()
        try:
            now = datetime.utcnow().isoformat()
            cursor = conn.execute(
                "UPDATE jobs SET status = 'queued', updated_at = ?, progress = 0 WHERE status = 'processing'",
                (now,)
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.warning(f"⚠️ Восстановлено {count} застрявших задач (processing -> queued)")
            return count
        finally:
            conn.close()


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
