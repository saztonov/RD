"""Supabase-хранилище для задач OCR (все данные в Supabase + R2)"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Any, Dict

from supabase import create_client, Client

from .settings import settings


@dataclass
class JobFile:
    id: str
    job_id: str
    file_type: str  # pdf|blocks|annotation|result_md|result_zip|crop
    r2_key: str
    file_name: str
    file_size: int
    created_at: str


@dataclass
class JobSettings:
    job_id: str
    text_model: str = ""
    table_model: str = ""
    image_model: str = ""


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
    engine: str
    r2_prefix: str
    node_id: Optional[str] = None  # ID узла дерева (для связи с деревом проектов)
    # Вложенные данные (опционально загружаются)
    files: List[JobFile] = field(default_factory=list)
    settings: Optional[JobSettings] = None


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
        client.table("jobs").select("id").limit(1).execute()
        logger.info("✅ Supabase: подключение установлено")
    except Exception as e:
        logger.error(f"❌ Supabase: ошибка подключения: {e}")
        raise


# === JOBS ===

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
    
    client = _get_client()
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
    client = _get_client()
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
    
    client = _get_client()
    client.table("jobs").update(updates).eq("id", job_id).execute()


def update_job_engine(job_id: str, engine: str) -> None:
    """Обновить engine задачи и перевести в queued"""
    now = datetime.utcnow().isoformat()
    client = _get_client()
    client.table("jobs").update({
        "engine": engine,
        "status": "queued",
        "updated_at": now
    }).eq("id", job_id).execute()


def count_processing_jobs() -> int:
    """Подсчитать количество задач в статусе processing"""
    client = _get_client()
    result = client.table("jobs").select("id", count="exact").eq("status", "processing").execute()
    return result.count or 0


def claim_next_job(max_concurrent: int = 2) -> Optional[Job]:
    """Взять следующую задачу в очереди (атомарно переключить в processing)"""
    client = _get_client()
    
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
        "updated_at": now
    }).eq("id", job_id).execute()
    return len(result.data) > 0


def recover_stuck_jobs() -> int:
    """При старте воркера: ставим ВСЕ активные задачи на паузу"""
    import logging
    logger = logging.getLogger(__name__)
    
    now = datetime.utcnow().isoformat()
    client = _get_client()
    
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
    client = _get_client()
    
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
    client = _get_client()
    result = client.table("jobs").update({
        "status": "queued",
        "updated_at": now
    }).eq("id", job_id).eq("status", "paused").execute()
    return len(result.data) > 0


def update_job_task_name(job_id: str, task_name: str) -> bool:
    """Обновить название задачи"""
    now = datetime.utcnow().isoformat()
    client = _get_client()
    result = client.table("jobs").update({
        "task_name": task_name,
        "updated_at": now
    }).eq("id", job_id).execute()
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
        "engine": job.engine,
        "r2_prefix": job.r2_prefix,
        "node_id": job.node_id
    }


# === JOB FILES ===

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
    
    client = _get_client()
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
    client = _get_client()
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
    client = _get_client()
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


# === JOB SETTINGS ===

def save_job_settings(
    job_id: str,
    text_model: str = "",
    table_model: str = "",
    image_model: str = ""
) -> JobSettings:
    """Сохранить/обновить настройки задачи"""
    now = datetime.utcnow().isoformat()
    client = _get_client()
    
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
    client = _get_client()
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


# === NODE FILES (связь с деревом проектов) ===

def get_node_file_by_type(node_id: str, file_type: str) -> Optional[Dict]:
    """Получить файл узла по типу (pdf, annotation и т.д.)"""
    client = _get_client()
    result = client.table("node_files").select("*").eq("node_id", node_id).eq("file_type", file_type).limit(1).execute()
    return result.data[0] if result.data else None


def get_node_pdf_r2_key(node_id: str) -> Optional[str]:
    """Получить r2_key PDF для узла (из node_files или tree_nodes.attributes)"""
    # Сначала пробуем node_files
    pdf_file = get_node_file_by_type(node_id, "pdf")
    if pdf_file:
        return pdf_file.get("r2_key")
    
    # Fallback: tree_nodes.attributes.r2_key
    client = _get_client()
    result = client.table("tree_nodes").select("attributes").eq("id", node_id).limit(1).execute()
    if result.data:
        attrs = result.data[0].get("attributes") or {}
        return attrs.get("r2_key")
    
    return None


def add_node_file(
    node_id: str,
    file_type: str,
    r2_key: str,
    file_name: str,
    file_size: int = 0,
    mime_type: str = "application/octet-stream",
    metadata: Optional[Dict] = None
) -> str:
    """Добавить файл к узлу дерева (upsert по node_id + r2_key)"""
    import logging
    logger = logging.getLogger(__name__)
    
    file_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    client = _get_client()
    try:
        client.table("node_files").upsert({
            "id": file_id,
            "node_id": node_id,
            "file_type": file_type,
            "r2_key": r2_key,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now
        }, on_conflict="node_id,r2_key").execute()
        logger.debug(f"Node file registered: {file_type} -> {r2_key}")
        return file_id
    except Exception as e:
        logger.warning(f"Failed to add node file: {e}")
        return ""


def register_ocr_results_to_node(node_id: str, doc_name: str, work_dir) -> int:
    """Зарегистрировать все OCR результаты в node_files.
    
    Файлы уже загружены в tree_docs/{node_id}/
    """
    import logging
    from pathlib import Path
    logger = logging.getLogger(__name__)
    
    if not node_id:
        return 0
    
    work_path = Path(work_dir)
    tree_prefix = f"tree_docs/{node_id}"
    registered = 0
    
    # result.md (переименован по имени документа)
    result_md = work_path / "result.md"
    if result_md.exists():
        doc_stem = Path(doc_name).stem
        md_filename = f"{doc_stem}.md"
        add_node_file(
            node_id, "result_md", f"{tree_prefix}/{md_filename}",
            md_filename, result_md.stat().st_size, "text/markdown"
        )
        registered += 1
    
    # annotation.json
    annotation = work_path / "annotation.json"
    if annotation.exists():
        add_node_file(
            node_id, "annotation", f"{tree_prefix}/annotation.json",
            "annotation.json", annotation.stat().st_size, "application/json"
        )
        registered += 1
    
    # crops/
    crops_dir = work_path / "crops"
    if crops_dir.exists():
        for crop_file in crops_dir.iterdir():
            if crop_file.is_file() and crop_file.suffix.lower() == ".pdf":
                add_node_file(
                    node_id, "crop", f"{tree_prefix}/crops/{crop_file.name}",
                    crop_file.name, crop_file.stat().st_size, "application/pdf"
                )
                registered += 1
    
    logger.info(f"Registered {registered} OCR result files for node {node_id}")
    return registered
