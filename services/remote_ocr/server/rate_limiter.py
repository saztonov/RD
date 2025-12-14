"""Глобальный rate limiter для Datalab API"""
from __future__ import annotations

import threading
import time
import logging

logger = logging.getLogger(__name__)


class DatalabRateLimiter:
    """
    Token Bucket rate limiter с ограничением параллельных запросов.
    
    Контролирует:
    - Максимум запросов в минуту (token bucket)
    - Максимум параллельных запросов (semaphore)
    """
    
    def __init__(
        self,
        max_requests_per_minute: int = 180,
        max_concurrent: int = 5
    ):
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
    """Получить глобальный rate limiter (lazy initialization)"""
    global _global_limiter
    
    if _global_limiter is None:
        with _limiter_lock:
            if _global_limiter is None:
                from .settings import settings
                _global_limiter = DatalabRateLimiter(
                    max_requests_per_minute=settings.datalab_max_rpm,
                    max_concurrent=settings.datalab_max_concurrent
                )
    
    return _global_limiter

