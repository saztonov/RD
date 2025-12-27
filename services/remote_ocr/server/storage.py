"""Supabase-хранилище для задач OCR (все данные в Supabase + R2)

Этот файл является фасадом для обратной совместимости.
Реализация разбита на модули:
- storage_models.py - модели данных
- storage_client.py - Supabase клиент
- storage_jobs.py - CRUD задач
- storage_files.py - файлы задач
- storage_settings.py - настройки задач
- storage_nodes.py - node_files (связь с деревом проектов)
"""

# Re-export моделей
from .storage_models import Job, JobFile, JobSettings

# Re-export клиента
from .storage_client import get_client, init_db

# Re-export CRUD задач
from .storage_jobs import (
    create_job,
    get_job,
    list_jobs,
    update_job_status,
    update_job_engine,
    update_job_task_name,
    count_processing_jobs,
    claim_next_job,
    delete_job,
    reset_job_for_restart,
    recover_stuck_jobs,
    pause_job,
    resume_job,
    is_job_paused,
)

# Re-export файлов задач
from .storage_files import (
    add_job_file,
    get_job_files,
    get_job_file_by_type,
    delete_job_files,
)

# Re-export настроек
from .storage_settings import (
    save_job_settings,
    get_job_settings,
)

# Re-export node files
from .storage_nodes import (
    get_node_file_by_type,
    get_node_pdf_r2_key,
    add_node_file,
    register_ocr_results_to_node,
)


def job_to_dict(job: Job) -> dict:
    """Конвертировать Job в dict для JSON ответа"""
    # Вычисляем result_prefix - папка где лежат результаты OCR
    result_prefix = job.r2_prefix
    if job.node_id:
        pdf_r2_key = get_node_pdf_r2_key(job.node_id)
        if pdf_r2_key:
            from pathlib import PurePosixPath
            result_prefix = str(PurePosixPath(pdf_r2_key).parent)
        else:
            result_prefix = f"tree_docs/{job.node_id}"
    
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
        "node_id": job.node_id,
        "result_prefix": result_prefix
    }
