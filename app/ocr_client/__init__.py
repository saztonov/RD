"""Модуль Remote OCR клиента"""

from app.ocr_client.client import RemoteOCRClient
from app.ocr_client.exceptions import (
    AuthenticationError,
    PayloadTooLargeError,
    RemoteOCRError,
    ServerError,
)
from app.ocr_client.models import JobInfo

__all__ = [
    "RemoteOCRClient",
    "JobInfo",
    "RemoteOCRError",
    "AuthenticationError",
    "PayloadTooLargeError",
    "ServerError",
]
