"""Конфигурация Celery для очереди OCR задач"""
from __future__ import annotations

from celery import Celery

from .settings import settings

celery_app = Celery(
    "ocr_worker",
    broker=settings.redis_url,
    backend=settings.redis_url
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Не prefetch задачи — воркер берёт по одной
    worker_prefetch_multiplier=1,
    # Таймауты
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Soft/hard time limits для задач (предотвращение зависания)
    task_soft_time_limit=1800,  # 30 min soft limit
    task_time_limit=2100,       # 35 min hard limit
    # Результаты храним 1 час
    result_expires=3600,
    # Ограничение памяти: перезапуск worker после N задач
    # При двухпроходном алгоритме можно увеличить до 100
    worker_max_tasks_per_child=100 if settings.use_two_pass_ocr else 50,
    # Concurrency: количество параллельных задач
    worker_concurrency=settings.max_concurrent_jobs,
    # Регистрация задач
    imports=["services.remote_ocr.server.tasks"],
)

