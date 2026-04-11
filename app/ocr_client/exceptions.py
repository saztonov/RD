"""Исключения Remote OCR клиента"""


class RemoteOCRError(Exception):
    """Базовая ошибка Remote OCR"""

    pass


class AuthenticationError(RemoteOCRError):
    """Неверный API ключ (401)"""

    pass


class PayloadTooLargeError(RemoteOCRError):
    """Слишком большой файл (413)"""

    pass


class ServerError(RemoteOCRError):
    """Ошибка сервера (5xx)"""

    pass


class JobNotFoundError(RemoteOCRError):
    """Задача не найдена на сервере (404) — orphan задача в клиентском кеше."""

    def __init__(self, job_id: str = "", message: str = ""):
        self.job_id = job_id
        super().__init__(message or f"Job not found on server: {job_id}")
