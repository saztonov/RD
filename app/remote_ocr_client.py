"""
HTTP-клиент для удалённого OCR сервера.

DEPRECATED: Этот модуль перемещён в app.ocr_client.
Этот файл сохранён для обратной совместимости.
"""
import warnings

warnings.warn(
    "Модуль app.remote_ocr_client устарел. "
    "Используйте app.ocr_client вместо него.",
    DeprecationWarning,
    stacklevel=2,
)

# Реэкспорт из нового модуля
from app.ocr_client import (
    AuthenticationError,
    JobInfo,
    PayloadTooLargeError,
    RemoteOCRClient,
    RemoteOCRError,
    RemoteOcrClient,
    ServerError,
    get_or_create_client_id,
)

__all__ = [
    "RemoteOCRClient",
    "RemoteOcrClient",
    "JobInfo",
    "RemoteOCRError",
    "AuthenticationError",
    "PayloadTooLargeError",
    "ServerError",
    "get_or_create_client_id",
]
