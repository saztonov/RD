"""Исключения для Block Detection API клиента."""


class BlockDetectionError(Exception):
    """Базовое исключение для ошибок Block Detection API."""

    pass


class BlockDetectionConnectionError(BlockDetectionError):
    """Ошибка подключения к серверу детекции."""

    pass


class BlockDetectionTimeoutError(BlockDetectionError):
    """Превышено время ожидания ответа."""

    pass


class BlockDetectionServerError(BlockDetectionError):
    """Ошибка на стороне сервера (5xx)."""

    pass
