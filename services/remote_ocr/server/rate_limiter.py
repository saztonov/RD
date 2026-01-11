"""Глобальный rate limiter для Datalab API и OpenRouter

DEPRECATED: Этот модуль использует threading-based rate limiting,
который не работает между процессами Celery.
Используйте redis_rate_limiter.py для распределённого rate limiting.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import warnings
from typing import Optional

logger = logging.getLogger(__name__)

# Флаг для отката на legacy rate limiter
USE_LEGACY_RATE_LIMITER = os.getenv("USE_LEGACY_RATE_LIMITER", "").lower() in ("1", "true", "yes")

# Глобальный семафор для ограничения ВСЕХ параллельных OCR запросов
_global_ocr_semaphore: threading.Semaphore | None = None
_global_ocr_lock = threading.Lock()


def get_global_ocr_semaphore(max_concurrent: int = 8) -> threading.Semaphore:
    """Глобальный семафор для всех OCR запросов (OpenRouter + Datalab)"""
    global _global_ocr_semaphore
    if _global_ocr_semaphore is None:
        with _global_ocr_lock:
            if _global_ocr_semaphore is None:
                _global_ocr_semaphore = threading.Semaphore(max_concurrent)
                logger.info(
                    f"Global OCR semaphore: {max_concurrent} concurrent requests"
                )
    return _global_ocr_semaphore


class DatalabRateLimiter:
    """
    Token Bucket rate limiter с ограничением параллельных запросов.

    Контролирует:
    - Максимум запросов в минуту (token bucket)
    - Максимум параллельных запросов (semaphore)
    """

    def __init__(self, max_requests_per_minute: int = 180, max_concurrent: int = 5):
        """
        Args:
            max_requests_per_minute: лимит запросов в минуту (с запасом от 200)
            max_concurrent: максимум параллельных запросов
        """
        self.max_requests = max_requests_per_minute
        self.period = 60.0  # секунд
        self.max_concurrent = max_concurrent

        # Token bucket
        self.tokens = float(max_requests_per_minute)
        self.last_refill = time.time()
        self._lock = threading.Lock()

        # Semaphore для ограничения параллельных запросов
        self._semaphore = threading.Semaphore(max_concurrent)

        # Статистика
        self._total_requests = 0
        self._total_waits = 0

        logger.info(
            f"DatalabRateLimiter: {max_requests_per_minute} req/min, "
            f"{max_concurrent} concurrent"
        )

    def _refill_tokens(self) -> None:
        """Пополнить токены на основе прошедшего времени"""
        now = time.time()
        elapsed = now - self.last_refill

        # Добавляем токены пропорционально прошедшему времени
        tokens_to_add = (elapsed / self.period) * self.max_requests
        self.tokens = min(self.max_requests, self.tokens + tokens_to_add)
        self.last_refill = now

    def acquire(self, timeout: float = 300.0) -> bool:
        """
        Получить разрешение на запрос к API.

        Args:
            timeout: максимальное время ожидания в секундах

        Returns:
            True если разрешение получено, False если таймаут
        """
        start_time = time.time()

        # Сначала ждём слот в semaphore (ограничение параллельных)
        if not self._semaphore.acquire(timeout=timeout):
            logger.warning("RateLimiter: таймаут ожидания semaphore")
            return False

        # Теперь ждём токен (ограничение по частоте)
        while True:
            with self._lock:
                self._refill_tokens()

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    self._total_requests += 1
                    return True

            # Проверяем таймаут
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                # Освобождаем semaphore если не смогли получить токен
                self._semaphore.release()
                logger.warning("RateLimiter: таймаут ожидания токена")
                return False

            # Ждём немного перед повторной проверкой
            wait_time = min(1.0, timeout - elapsed)
            self._total_waits += 1
            logger.debug(f"RateLimiter: ожидание токена ({self.tokens:.1f} tokens)")
            time.sleep(wait_time)

    def release(self) -> None:
        """Освободить слот после завершения запроса"""
        self._semaphore.release()

    def get_stats(self) -> dict:
        """Получить статистику использования"""
        with self._lock:
            return {
                "total_requests": self._total_requests,
                "total_waits": self._total_waits,
                "current_tokens": self.tokens,
                "max_requests_per_minute": self.max_requests,
                "max_concurrent": self.max_concurrent,
            }


# Глобальный экземпляр (инициализируется при импорте settings)
_global_limiter: DatalabRateLimiter | None = None
_limiter_lock = threading.Lock()


def get_datalab_limiter() -> DatalabRateLimiter:
    """
    Получить глобальный rate limiter (lazy initialization).

    DEPRECATED: Используйте CompatRateLimiter("datalab") для распределённого rate limiting.
    """
    global _global_limiter

    if not USE_LEGACY_RATE_LIMITER:
        warnings.warn(
            "get_datalab_limiter() is deprecated, use CompatRateLimiter('datalab')",
            DeprecationWarning,
            stacklevel=2,
        )

    if _global_limiter is None:
        with _limiter_lock:
            if _global_limiter is None:
                from .settings import settings

                _global_limiter = DatalabRateLimiter(
                    max_requests_per_minute=settings.datalab_max_rpm,
                    max_concurrent=settings.datalab_max_concurrent,
                )

    return _global_limiter


class CompatRateLimiter:
    """
    Обратно-совместимый wrapper для Redis rate limiter.

    Предоставляет старый API acquire(timeout)/release() для совместимости
    с существующим кодом, делегируя в RedisRateLimiter.

    Usage:
        limiter = CompatRateLimiter("datalab", {"job_id": "123"})
        if limiter.acquire():
            try:
                # ... API call ...
            finally:
                limiter.release()
    """

    def __init__(
        self,
        engine: str,
        context: Optional[dict] = None,
    ):
        """
        Args:
            engine: OCR движок ("datalab", "openrouter", "client")
            context: дополнительный контекст (job_id, model_name)
        """
        self._engine = engine
        self._context = context or {}
        self._slot_id: Optional[str] = None
        self._use_legacy = USE_LEGACY_RATE_LIMITER

        # Lazy init для избежания circular imports
        self._redis_limiter = None
        self._legacy_limiter = None

    def _get_limiter(self):
        """Получить limiter (lazy init)"""
        if self._use_legacy:
            if self._legacy_limiter is None:
                if self._engine == "datalab":
                    self._legacy_limiter = get_datalab_limiter()
                else:
                    # Для других движков используем глобальный семафор
                    self._legacy_limiter = None
            return self._legacy_limiter
        else:
            if self._redis_limiter is None:
                from .redis_rate_limiter import get_redis_rate_limiter

                self._redis_limiter = get_redis_rate_limiter()
            return self._redis_limiter

    def acquire(self, timeout: float = 300.0) -> bool:
        """
        Получить разрешение на запрос.

        Args:
            timeout: максимальное время ожидания в секундах

        Returns:
            True если разрешение получено, False если таймаут
        """
        if self._use_legacy:
            limiter = self._get_limiter()
            if limiter:
                return limiter.acquire(timeout=timeout)
            # Fallback: используем глобальный семафор
            sem = get_global_ocr_semaphore()
            return sem.acquire(timeout=timeout)
        else:
            limiter = self._get_limiter()
            result = limiter.acquire(
                engine=self._engine,
                timeout=timeout,
                context=self._context,
            )
            if result.success:
                self._slot_id = result.slot_id
            return result.success

    def release(self) -> None:
        """Освободить слот после завершения запроса"""
        if self._use_legacy:
            limiter = self._get_limiter()
            if limiter:
                limiter.release()
            else:
                # Fallback: используем глобальный семафор
                sem = get_global_ocr_semaphore()
                try:
                    sem.release()
                except ValueError:
                    pass
        else:
            if self._slot_id:
                limiter = self._get_limiter()
                limiter.release(self._engine, slot_id=self._slot_id)
                self._slot_id = None

    def report_429(self, retry_after: Optional[int] = None) -> None:
        """
        Сообщить о получении 429 от API.

        Args:
            retry_after: значение из заголовка Retry-After (секунды)
        """
        if not self._use_legacy:
            limiter = self._get_limiter()
            limiter.report_429(self._engine, retry_after)

    def get_stats(self) -> dict:
        """Получить статистику использования"""
        if self._use_legacy:
            limiter = self._get_limiter()
            if limiter and hasattr(limiter, "get_stats"):
                return limiter.get_stats()
            return {}
        else:
            limiter = self._get_limiter()
            status = limiter.get_status(self._engine)
            return {
                "engine": status.engine,
                "current_concurrent": status.current_concurrent,
                "max_concurrent": status.max_concurrent,
                "requests_in_window": status.requests_in_window,
                "max_rpm": status.max_requests_per_window,
                "backoff_until": status.backoff_until,
            }
