"""Общие утилиты для routes"""
from typing import Optional
from fastapi import HTTPException, Header

from services.remote_ocr.server.settings import settings


def check_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    """Проверить API ключ если он задан в настройках"""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def get_r2_storage():
    """Получить R2 Storage клиент (async-обёртка)"""
    from services.remote_ocr.server.async_r2_storage import AsyncR2StorageSync
    return AsyncR2StorageSync()


def get_r2_sync_client():
    """Получить синхронный boto3 клиент для прямых операций (put_object и т.д.)"""
    import os
    import boto3
    from botocore.config import Config
    
    account_id = os.getenv("R2_ACCOUNT_ID")
    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com" if account_id else os.getenv("R2_ENDPOINT_URL")
    bucket_name = os.getenv("R2_BUCKET_NAME", "rd1")
    
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(retries={"max_attempts": 3}),
    )
    return client, bucket_name


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

