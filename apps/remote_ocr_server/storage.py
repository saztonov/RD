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

# Re-export клиента
from .storage_client import get_client, init_db

# Re-export файлов задач
from .storage_files import (
    add_job_file,
    delete_job_files,
    get_job_file_by_type,
    get_job_files,
)

# Re-export CRUD задач
from .storage_jobs import (
    create_job,
    delete_job,
    get_job,
    list_jobs,
    list_jobs_changed_since,
    log_db_metrics,
    reset_job_for_restart,
    update_job_completed,
    update_job_engine,
    update_job_started,
    update_job_status,
    update_job_task_name,
)

# Re-export моделей
from .storage_models import Job, JobFile, JobSettings

# Re-export node files и tree_nodes
from .node_storage import (
    add_node_file,
    create_node,
    delete_node,
    delete_node_file,
    get_children,
    get_node,
    get_node_file_by_type,
    get_node_files,
    get_node_full_path,
    get_node_info,
    get_node_pdf_r2_key,
    get_root_nodes,
    register_ocr_results_to_node,
    update_node,
    update_node_pdf_status,
    update_node_r2_key,
    update_pdf_status,
)

# Re-export настроек
from .storage_settings import get_job_settings, save_job_settings


def job_to_dict(job: Job) -> dict:
    """Конвертировать Job в dict для JSON ответа.

    Структура R2: tree_docs/{node_id}/
        {doc_name}.pdf
        {doc_stem}_result.md
        crops/{block_id}.pdf
    """
    from .r2_paths import get_doc_prefix

    # Структура: r2_prefix = tree_docs/{node_id}
    # ocr_result_prefix совпадает с r2_prefix
    r2_prefix = job.r2_prefix
    if job.node_id:
        r2_prefix = get_doc_prefix(job.node_id)

    return {
        "id": job.id,
        "document_id": job.document_id,
        "document_name": job.document_name,
        "task_name": job.task_name,
        "status": job.status,
        "progress": job.progress,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error_message": job.error_message,
        "engine": job.engine,
        "r2_prefix": r2_prefix,
        "node_id": job.node_id,
        "result_prefix": r2_prefix,  # теперь совпадает с r2_prefix
        "ocr_result_prefix": r2_prefix,  # теперь совпадает с r2_prefix
        "status_message": job.status_message,
        "block_stats": job.block_stats,
    }
