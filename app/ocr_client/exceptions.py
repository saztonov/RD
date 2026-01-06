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
