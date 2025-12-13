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


settings = Settings()
