"""Проверка размера очереди Redis для backpressure"""
from __future__ import annotations

import threading
from urllib.parse import urlparse

import redis

from .settings import settings

# Thread-safe connection pool для Redis
_redis_pool: redis.ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_redis_pool() -> redis.ConnectionPool:
    """Получить Redis connection pool (thread-safe singleton)"""
    global _redis_pool
    if _redis_pool is None:
        with _pool_lock:
            if _redis_pool is None:  # double-check
                parsed = urlparse(settings.redis_url)
                _redis_pool = redis.ConnectionPool(
                    host=parsed.hostname or "localhost",
                    port=parsed.port or 6379,
                    db=int(parsed.path.lstrip("/") or 0),
                    password=parsed.password,
                    decode_responses=True,
                    max_connections=10,
                )
    return _redis_pool


def _get_redis_client() -> redis.Redis:
    """Получить Redis клиент с connection pooling"""
    return redis.Redis(connection_pool=_get_redis_pool())


def get_queue_size() -> int:
    """Получить текущий размер очереди Celery"""
    try:
        client = _get_redis_client()
        # Celery default queue name
        return client.llen("celery")
    except Exception:
        return 0


def is_queue_full() -> bool:
    """Проверить, переполнена ли очередь"""
    if settings.max_queue_size <= 0:
        return False  # Без лимита
    return get_queue_size() >= settings.max_queue_size


def check_queue_capacity() -> tuple[bool, int, int]:
    """Проверить ёмкость очереди.

    Returns:
        (can_accept, current_size, max_size)
    """
    current = get_queue_size()
    max_size = settings.max_queue_size
    can_accept = max_size <= 0 or current < max_size
    return can_accept, current, max_size
