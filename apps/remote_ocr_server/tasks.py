"""Celery задачи для OCR обработки.

Thin wrapper над JobOrchestrator - вся логика в job_orchestrator.py.
"""
from __future__ import annotations

import logging
import traceback

from .celery_app import celery_app
from .job_orchestrator import JobOrchestrator
from .memory_utils import force_gc, log_memory, log_memory_delta
from .storage import get_job, log_db_metrics, update_job_completed, update_job_started, update_job_status
from .worker_pdf import clear_page_size_cache

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="run_ocr_task", max_retries=3, rate_limit="4/m")
def run_ocr_task(self, job_id: str) -> dict:
    """Celery задача для обработки OCR.

    Делегирует всю работу JobOrchestrator для лучшей тестируемости
    и разделения ответственности.
    """
    start_mem = log_memory(f"[START] Задача {job_id}")
    orchestrator = JobOrchestrator(job_id)

    try:
        # Получаем задачу из БД
        job = get_job(job_id, with_files=True, with_settings=True)
        if not job:
            logger.error(f"Задача {job_id} не найдена")
            return {"status": "error", "message": "Job not found"}

        # Стартуем задачу
        update_job_started(job.id)
        orchestrator.update_status("processing", 0.05, "Инициализация задачи...")

        # Настройка рабочего пространства
        orchestrator.setup_workspace()

        # Скачивание файлов
        orchestrator.download_files(job)
        log_memory_delta("После скачивания файлов", start_mem)

        # Парсинг блоков
        blocks = orchestrator.parse_blocks()

        if not blocks:
            orchestrator.handle_empty_blocks(job)
            return {"status": "done", "job_id": job_id}

        # Создание OCR движков
        engines = orchestrator.create_engines(job)

        # OCR обработка
        orchestrator.run_ocr(job, engines, start_mem)
        force_gc("после OCR обработки")

        # Генерация и загрузка результатов
        orchestrator.generate_and_upload_results(job, engines)

        # Регистрация файлов для node
        orchestrator.register_node_files(job)

        # Статистика и завершение
        block_stats = orchestrator.calculate_stats()
        update_job_completed(job.id, block_stats=block_stats)
        update_job_status(job.id, "done", progress=1.0, status_message="Завершено успешно", force=True)

        logger.info(f"Задача {job.id} завершена. Статистика: {block_stats}")
        return {"status": "done", "job_id": job_id}

    except Exception as e:
        error_msg = f"{e}\n{traceback.format_exc()}"
        logger.error(f"Ошибка обработки задачи {job_id}: {error_msg}")
        update_job_completed(job_id, error_message=str(e))
        update_job_status(job_id, "error", error_message=str(e), status_message="Ошибка обработки", force=True)
        return {"status": "error", "message": str(e)}

    finally:
        # Очистка
        orchestrator.cleanup()
        clear_page_size_cache()
        log_db_metrics(job_id)
        force_gc("финальная")
        log_memory_delta(f"[END] Задача {job_id}", start_mem)
