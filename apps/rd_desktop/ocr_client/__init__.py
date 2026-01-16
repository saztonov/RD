"""Модуль Remote OCR клиента"""

from apps.rd_desktop.ocr_client.client import RemoteOCRClient
from apps.rd_desktop.ocr_client.exceptions import (
    AuthenticationError,
    PayloadTooLargeError,
    RemoteOCRError,
    ServerError,
)
from apps.rd_desktop.ocr_client.models import JobInfo

__all__ = [
    "RemoteOCRClient",
    "JobInfo",
    "RemoteOCRError",
    "AuthenticationError",
    "PayloadTooLargeError",
    "ServerError",
]
