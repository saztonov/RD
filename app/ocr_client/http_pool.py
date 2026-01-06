"""HTTP connection pooling для Remote OCR клиента"""
from __future__ import annotations

import os
import platform
import uuid
from pathlib import Path

import httpx
from httpx import Limits

# Глобальный пул соединений для Remote OCR
_remote_ocr_http_client: httpx.Client | None = None
_remote_ocr_base_url: str | None = None


def get_remote_ocr_client(base_url: str, timeout: float = 120.0) -> httpx.Client:
    """Получить или создать HTTP клиент с connection pooling"""
    global _remote_ocr_http_client, _remote_ocr_base_url
    if _remote_ocr_http_client is None or _remote_ocr_base_url != base_url:
        if _remote_ocr_http_client is not None:
            try:
                _remote_ocr_http_client.close()
            except Exception:
                pass
        _remote_ocr_http_client = httpx.Client(
            base_url=base_url,
            limits=Limits(max_connections=10, max_keepalive_connections=5),
            timeout=timeout,
        )
        _remote_ocr_base_url = base_url
    return _remote_ocr_http_client


def get_client_id_path() -> Path:
    """Получить путь к файлу client_id"""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    return base / "RD" / "client_id.txt"


def get_or_create_client_id() -> str:
    """Получить или создать client_id"""
    # Сначала проверяем env
    env_id = os.getenv("REMOTE_OCR_CLIENT_ID")
    if env_id:
        return env_id

    # Иначе читаем/создаём файл
    id_path = get_client_id_path()

    if id_path.exists():
        try:
            return id_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    # Генерируем новый
    new_id = str(uuid.uuid4())
    try:
        id_path.parent.mkdir(parents=True, exist_ok=True)
        id_path.write_text(new_id, encoding="utf-8")
    except Exception:
        pass  # Если не получилось сохранить, используем временный

    return new_id
