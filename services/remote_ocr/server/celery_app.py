"""Конфигурация Celery для очереди OCR задач"""
from __future__ import annotations

from celery import Celery
from kombu import Queue

from .settings import settings

celery_app = Celery("ocr_worker", broker=settings.redis_url, backend=settings.redis_url)

# Определение очередей для разных типов OCR задач
celery_app.conf.task_queues = (
    Queue("celery", routing_key="celery"),  # Legacy (default)
    Queue("ocr_meta", routing_key="ocr.meta"),  # Координационные задачи
    Queue("ocr_text", routing_key="ocr.text"),  # TEXT/TABLE блоки
    Queue("ocr_image", routing_key="ocr.image"),  # IMAGE блоки
    Queue("ocr_stamp", routing_key="ocr.stamp"),  # STAMP блоки
)

# Маршрутизация задач по очередям
celery_app.conf.task_routes = {
    "run_ocr_task": {"queue": "celery"},  # Legacy
    "run_ocr_job": {"queue": "ocr_meta"},
    "process_strips": {"queue": "ocr_text"},
    "process_images": {"queue": "ocr_image"},
    "process_stamps": {"queue": "ocr_stamp"},
    "collect_ocr_results": {"queue": "ocr_meta"},
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # ===== WORKER =====
    # Concurrency: количество параллельных задач
    worker_concurrency=settings.max_concurrent_jobs,
    # Prefetch: сколько задач брать заранее
    worker_prefetch_multiplier=settings.worker_prefetch,
    # Перезапуск воркера после N задач (защита от утечек памяти)
    worker_max_tasks_per_child=settings.worker_max_tasks,
    # ===== ЗАДАЧИ =====
    # Подтверждение после выполнения (не терять при падении)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Soft/hard time limits
    task_soft_time_limit=settings.task_soft_timeout,
    task_time_limit=settings.task_hard_timeout,
    # Retry
    task_default_retry_delay=settings.task_retry_delay,
    # ===== РЕЗУЛЬТАТЫ =====
    # Результаты храним 2 часа (для chord)
    result_expires=7200,
    # ===== ОЧЕРЕДЬ =====
    # Приоритет (требует Redis)
    task_default_priority=settings.default_task_priority,
    task_queue_max_priority=10,
    # ===== CHORD =====
    # Настройки для chord (группировка задач)
    chord_unlock_max_retries=60,
    chord_unlock_retry_delay=5,
    # Регистрация задач
    imports=[
        "services.remote_ocr.server.tasks",
    ],
)
