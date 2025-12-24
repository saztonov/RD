from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Настройки remote OCR сервера"""
    data_dir: str = os.getenv("REMOTE_OCR_DATA_DIR", "/data")
    api_key: str = os.getenv("REMOTE_OCR_API_KEY", "")  # Если задан, требуем X-API-Key
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    datalab_api_key: str = os.getenv("DATALAB_API_KEY", "")
    
    # Redis (брокер Celery)
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    
    # Supabase
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    
    # Лимиты Datalab API (для глобального rate limiter)
    datalab_max_rpm: int = int(os.getenv("DATALAB_MAX_RPM", "180"))  # запросов/минуту
    datalab_max_concurrent: int = int(os.getenv("DATALAB_MAX_CONCURRENT", "5"))  # параллельных
    
    # Лимит параллельных задач (job-ов) - остальные ждут в очереди
    max_concurrent_jobs: int = int(os.getenv("MAX_CONCURRENT_JOBS", "4"))
    
    # Глобальный лимит параллельных OCR запросов (все задачи суммарно)
    max_global_ocr_requests: int = int(os.getenv("MAX_GLOBAL_OCR_REQUESTS", "8"))
    
    # Количество OCR потоков внутри одной задачи
    ocr_threads_per_job: int = int(os.getenv("OCR_THREADS_PER_JOB", "2"))
    
    # Использовать двухпроходный алгоритм (экономия памяти)
    use_two_pass_ocr: bool = os.getenv("USE_TWO_PASS_OCR", "true").lower() in ("true", "1", "yes")
    
    # Качество сохранения PNG кропов (0-9, 0=без сжатия, 9=максимальное)
    crop_png_compress: int = int(os.getenv("CROP_PNG_COMPRESS", "6"))
    
    # Максимальный размер batch для OCR (группировка strips)
    max_ocr_batch_size: int = int(os.getenv("MAX_OCR_BATCH_SIZE", "5"))
    
    # Интервал polling очереди (сек)
    poll_interval: float = float(os.getenv("POLL_INTERVAL", "10"))
    poll_max_interval: float = float(os.getenv("POLL_MAX_INTERVAL", "60"))
    
    # Backpressure: максимальный размер очереди Redis
    max_queue_size: int = int(os.getenv("MAX_QUEUE_SIZE", "100"))


settings = Settings()
