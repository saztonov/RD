"""Модель данных для настроек OCR сервера."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class OCRSettings:
    """Настройки OCR сервера"""

    # Celery Worker
    max_concurrent_jobs: int = 4
    worker_prefetch: int = 1
    worker_max_tasks: int = 100
    task_soft_timeout: int = 1800
    task_hard_timeout: int = 2100
    task_max_retries: int = 3
    task_retry_delay: int = 60

    # OCR Threading
    max_global_ocr_requests: int = 8
    ocr_threads_per_job: int = 2
    ocr_request_timeout: int = 120

    # Datalab API
    datalab_max_rpm: int = 180
    datalab_max_concurrent: int = 5
    datalab_poll_interval: int = 3
    datalab_poll_max_attempts: int = 90
    datalab_max_retries: int = 3

    # Двухпроходный алгоритм
    use_two_pass_ocr: bool = True
    crop_png_compress: int = 6
    max_ocr_batch_size: int = 5
    pdf_render_dpi: int = 300
    max_strip_height: int = 9000

    # Очередь
    poll_interval: float = 10.0
    poll_max_interval: float = 60.0
    max_queue_size: int = 100
    default_task_priority: int = 5

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "OCRSettings":
        # Фильтруем только известные поля
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)
