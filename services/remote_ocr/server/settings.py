from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("REMOTE_OCR_HOST", "0.0.0.0")
    port: int = int(os.getenv("REMOTE_OCR_PORT", "8081"))
    data_dir: str = os.getenv("REMOTE_OCR_DATA_DIR", "/workspace/.remote_ocr")


settings = Settings()


