"""
HTTP-клиент для удалённого OCR сервера.

DEPRECATED: Этот модуль перемещён в app.ocr_client.
Этот файл сохранён для обратной совместимости.
"""
# Реэкспорт из нового модуля
from app.ocr_client import (
    AuthenticationError,
    JobInfo,
    PayloadTooLargeError,
    RemoteOCRClient,
    RemoteOCRError,
    RemoteOcrClient,
    ServerError,
)
from app.ocr_client.http_pool import get_or_create_client_id as _get_or_create_client_id

__all__ = [
    "RemoteOCRClient",
    "RemoteOcrClient",
    "JobInfo",
    "RemoteOCRError",
    "AuthenticationError",
    "PayloadTooLargeError",
    "ServerError",
    "_get_or_create_client_id",
]
