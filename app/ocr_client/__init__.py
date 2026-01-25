"""
Модуль Remote OCR клиента.

Компоненты:
- client.py - RemoteOCRClient
- utils.py - get_or_create_client_id, hash_pdf
- models.py - JobInfo
- exceptions.py - RemoteOCRError, AuthenticationError, etc.
- http_pool.py - Connection pooling
"""

from app.ocr_client.client import RemoteOCRClient, RemoteOcrClient
from app.ocr_client.exceptions import (
    AuthenticationError,
    PayloadTooLargeError,
    RemoteOCRError,
    ServerError,
)
from app.ocr_client.models import JobInfo
from app.ocr_client.utils import get_or_create_client_id, hash_pdf

__all__ = [
    "RemoteOCRClient",
    "RemoteOcrClient",
    "JobInfo",
    "RemoteOCRError",
    "AuthenticationError",
    "PayloadTooLargeError",
    "ServerError",
    "get_or_create_client_id",
    "hash_pdf",
]
