from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

# NOTE: settings.py загружается раньше logging_config, поэтому используем стандартный logging
logger = logging.getLogger(__name__)


def _load_settings_from_supabase() -> Optional[dict]:
    """Загрузить настройки из Supabase"""
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_KEY", "")

    if not supabase_url or not supabase_key:
        return None

    try:
        import httpx

        url = f"{supabase_url}/rest/v1/app_settings?key=eq.ocr_server_settings"
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    logger.info("OCR settings loaded from Supabase")
                    return data[0].get("value", {})
    except Exception as e:
        logger.warning(f"Failed to load settings from Supabase: {e}")

    return None


def _get_setting(
    db_settings: Optional[dict], key: str, env_key: str, default, cast_fn=None
):
    """Получить настройку: сначала из БД, потом из env, потом default"""
    # Приоритет: БД > env > default
    if db_settings and key in db_settings:
        value = db_settings[key]
    elif os.getenv(env_key):
        value = os.getenv(env_key)
    else:
        return default

    if cast_fn:
        try:
            return cast_fn(value)
        except:
            return default
    return value


# Загружаем настройки из БД один раз при импорте модуля
_db_settings = _load_settings_from_supabase()


@dataclass
class Settings:
    """Настройки remote OCR сервера (загружаются из Supabase или env)"""

    # ===== СИСТЕМНЫЕ (только env) =====
    data_dir: str = field(
        default_factory=lambda: os.getenv("REMOTE_OCR_DATA_DIR", "/data")
    )
    api_key: str = field(default_factory=lambda: os.getenv("REMOTE_OCR_API_KEY", ""))
    openrouter_api_key: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "")
    )
    datalab_api_key: str = field(
        default_factory=lambda: os.getenv("DATALAB_API_KEY", "")
    )
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://redis:6379/0")
    )
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))

    # ===== CELERY WORKER =====
    max_concurrent_jobs: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "max_concurrent_jobs", "MAX_CONCURRENT_JOBS", 4, int
        )
    )
    worker_prefetch: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "worker_prefetch", "WORKER_PREFETCH", 1, int
        )
    )
    worker_max_tasks: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "worker_max_tasks", "WORKER_MAX_TASKS", 100, int
        )
    )
    task_soft_timeout: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "task_soft_timeout", "TASK_SOFT_TIMEOUT", 3000, int
        )
    )
    task_hard_timeout: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "task_hard_timeout", "TASK_HARD_TIMEOUT", 3600, int
        )
    )
    task_max_retries: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "task_max_retries", "TASK_MAX_RETRIES", 3, int
        )
    )
    task_retry_delay: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "task_retry_delay", "TASK_RETRY_DELAY", 60, int
        )
    )

    # ===== OCR THREADING =====
    max_global_ocr_requests: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "max_global_ocr_requests", "MAX_GLOBAL_OCR_REQUESTS", 8, int
        )
    )
    ocr_threads_per_job: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "ocr_threads_per_job", "OCR_THREADS_PER_JOB", 2, int
        )
    )
    ocr_request_timeout: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "ocr_request_timeout", "OCR_REQUEST_TIMEOUT", 120, int
        )
    )

    # ===== DATALAB API =====
    datalab_max_rpm: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "datalab_max_rpm", "DATALAB_MAX_RPM", 180, int
        )
    )
    datalab_max_concurrent: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "datalab_max_concurrent", "DATALAB_MAX_CONCURRENT", 5, int
        )
    )
    datalab_poll_interval: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "datalab_poll_interval", "DATALAB_POLL_INTERVAL", 3, int
        )
    )
    datalab_poll_max_attempts: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "datalab_poll_max_attempts", "DATALAB_POLL_MAX_ATTEMPTS", 90, int
        )
    )
    datalab_max_retries: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "datalab_max_retries", "DATALAB_MAX_RETRIES", 3, int
        )
    )

    # ===== НАСТРОЙКИ OCR =====
    crop_png_compress: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "crop_png_compress", "CROP_PNG_COMPRESS", 6, int
        )
    )
    max_ocr_batch_size: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "max_ocr_batch_size", "MAX_OCR_BATCH_SIZE", 5, int
        )
    )
    pdf_render_dpi: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "pdf_render_dpi", "PDF_RENDER_DPI", 300, int
        )
    )
    max_strip_height: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "max_strip_height", "MAX_STRIP_HEIGHT", 9000, int
        )
    )

    # ===== ОЧЕРЕДЬ =====
    poll_interval: float = field(
        default_factory=lambda: _get_setting(
            _db_settings, "poll_interval", "POLL_INTERVAL", 10.0, float
        )
    )
    poll_max_interval: float = field(
        default_factory=lambda: _get_setting(
            _db_settings, "poll_max_interval", "POLL_MAX_INTERVAL", 60.0, float
        )
    )
    max_queue_size: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "max_queue_size", "MAX_QUEUE_SIZE", 100, int
        )
    )
    default_task_priority: int = field(
        default_factory=lambda: _get_setting(
            _db_settings, "default_task_priority", "DEFAULT_TASK_PRIORITY", 5, int
        )
    )


settings = Settings()
