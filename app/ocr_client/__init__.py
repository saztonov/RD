"""Модуль Remote OCR клиента"""

from app.ocr_client.client import RemoteOCRClient, RemoteOcrClient
from app.ocr_client.exceptions import (
    AuthenticationError,
    PayloadTooLargeError,
    RemoteOCRError,
    ServerError,
)
from app.ocr_client.models import JobInfo

__all__ = [
    "RemoteOCRClient",
    "RemoteOcrClient",
    "JobInfo",
    "RemoteOCRError",
    "AuthenticationError",
    "PayloadTooLargeError",
    "ServerError",
]
