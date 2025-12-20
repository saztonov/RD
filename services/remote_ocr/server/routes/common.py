"""Общие утилиты для routes"""
from typing import Optional
from fastapi import HTTPException, Header

from services.remote_ocr.server.settings import settings


def check_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    """Проверить API ключ если он задан в настройках"""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def get_r2_storage():
    """Получить R2 Storage клиент"""
    from rd_core.r2_storage import R2Storage
    return R2Storage()


def get_file_icon(file_type: str) -> str:
    """Получить иконку для типа файла"""
    icons = {
        "pdf": "📄",
        "blocks": "📋",
        "annotation": "📋",
        "result_md": "📝",
        "result_zip": "📦",
        "crop": "🖼️"
    }
    return icons.get(file_type, "📄")

