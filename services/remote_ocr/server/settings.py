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
    
    # Supabase
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    
    # Лимиты Datalab API (для глобального rate limiter)
    datalab_max_rpm: int = int(os.getenv("DATALAB_MAX_RPM", "180"))  # запросов/минуту
    datalab_max_concurrent: int = int(os.getenv("DATALAB_MAX_CONCURRENT", "5"))  # параллельных
    
    # Лимит параллельных задач (job-ов) - остальные ждут в очереди
    max_concurrent_jobs: int = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
    
    # Интервал polling очереди (сек)
    poll_interval: float = float(os.getenv("POLL_INTERVAL", "10"))
    poll_max_interval: float = float(os.getenv("POLL_MAX_INTERVAL", "60"))


settings = Settings()
