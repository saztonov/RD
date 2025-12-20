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
    # Результаты храним 1 час
    result_expires=3600,
)

