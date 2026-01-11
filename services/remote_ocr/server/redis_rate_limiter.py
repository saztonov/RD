"""Распределённый Rate Limiter на Redis для кластера Celery OCR"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import redis

logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    """Конфигурация лимитов для движка"""

    max_rpm: int  # запросов в минуту
    max_concurrent: int  # макс параллельных запросов
    window_seconds: int = 60


@dataclass
class AcquireResult:
    """Результат acquire()"""

    success: bool
    wait_time: float = 0.0
    slot_id: Optional[str] = None
    retry_after: Optional[float] = None


@dataclass
class RateLimiterStatus:
    """Статус rate limiter для мониторинга"""

    engine: str
    current_concurrent: int
    max_concurrent: int
    requests_in_window: int
    max_requests_per_window: int
    backoff_until: Optional[float] = None


# Конфигурация по умолчанию
DEFAULT_ENGINE_CONFIGS = {
    "datalab": EngineConfig(max_rpm=180, max_concurrent=5),
    "openrouter": EngineConfig(max_rpm=60, max_concurrent=8),
    "client": EngineConfig(max_rpm=30, max_concurrent=4),
    "global": EngineConfig(max_rpm=500, max_concurrent=20),
}


class RedisRateLimiter:
    """
    Распределённый rate limiter с:
    - Sliding window counter для RPM (ZSET)
    - Distributed semaphore для параллельных запросов (SET)
    - Backoff при 429 ошибках (STRING с TTL)
    """

    # Redis key prefixes
    KEY_COUNTER = "rate_limit:counter"  # Sliding window counter
    KEY_SEMAPHORE = "rate_limit:sem"  # Distributed semaphore
    KEY_BACKOFF = "rate_limit:backoff"  # Backoff state

    SLOT_TTL = 600  # TTL для семафора слотов (защита от deadlock)

    def __init__(
        self,
        redis_url: str,
        engine_configs: Optional[dict[str, EngineConfig]] = None,
        backoff_base: float = 5.0,
        backoff_max: float = 60.0,
    ):
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self.configs = engine_configs or DEFAULT_ENGINE_CONFIGS.copy()
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max

        # Fallback на локальный семафор при недоступности Redis
        self._local_sem: Optional[threading.Semaphore] = None
        self._local_lock = threading.Lock()

    def _get_config(self, engine: str) -> EngineConfig:
        """Получить конфигурацию для движка"""
        return self.configs.get(engine, EngineConfig(max_rpm=30, max_concurrent=2))

    def acquire(
        self,
        engine: str,
        key: str = "global",
        cost: int = 1,
        timeout: float = 300.0,
        context: Optional[dict] = None,
    ) -> AcquireResult:
        """
        Получить разрешение на запрос к API.

        Args:
            engine: OCR движок (datalab, openrouter, client)
            key: ключ лимита (обычно "global" или client_id)
            cost: стоимость запроса в токенах
            timeout: максимальное время ожидания в секундах
            context: дополнительный контекст (job_id, model_name)

        Returns:
            AcquireResult с результатом
        """
        try:
            return self._acquire_redis(engine, key, cost, timeout)
        except redis.ConnectionError as e:
            logger.warning(f"Redis unavailable, falling back to local: {e}")
            return self._acquire_local(timeout)
        except Exception as e:
            logger.error(f"Rate limiter error: {e}")
            # Fail-open: пропускаем при ошибке
            return AcquireResult(success=True, slot_id=str(uuid.uuid4()))

    def _acquire_redis(
        self,
        engine: str,
        key: str,
        cost: int,
        timeout: float,
    ) -> AcquireResult:
        """Acquire через Redis"""
        config = self._get_config(engine)
        start_time = time.time()
        slot_id = str(uuid.uuid4())

        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                return AcquireResult(
                    success=False,
                    wait_time=elapsed,
                    retry_after=5.0,
                )

            # 1. Проверяем backoff
            backoff_key = f"{self.KEY_BACKOFF}:{engine}"
            backoff_until = self.redis.get(backoff_key)
            if backoff_until:
                wait = float(backoff_until) - time.time()
                if wait > 0:
                    sleep_time = min(wait, 1.0, timeout - elapsed)
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    continue

            # 2. Пытаемся захватить semaphore slot
            sem_key = f"{self.KEY_SEMAPHORE}:{engine}"
            current = self.redis.scard(sem_key)

            if current >= config.max_concurrent:
                # Очищаем истёкшие слоты
                self._cleanup_expired_slots(engine)
                time.sleep(0.5)
                continue

            # Атомарно добавляем слот
            added = self.redis.sadd(sem_key, slot_id)
            if not added:
                continue

            # Устанавливаем TTL на slot (защита от deadlock)
            slot_ttl_key = f"{sem_key}:slot:{slot_id}"
            self.redis.setex(slot_ttl_key, self.SLOT_TTL, "1")

            # 3. Проверяем sliding window
            counter_key = f"{self.KEY_COUNTER}:{engine}:{key}"
            now = time.time()
            window_start = now - config.window_seconds

            # Удаляем старые записи, добавляем новую
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(counter_key, "-inf", window_start)
            pipe.zadd(counter_key, {f"{now}:{slot_id}": now})
            pipe.zcard(counter_key)
            pipe.expire(counter_key, config.window_seconds * 2)
            results = pipe.execute()

            count = results[2]

            if count > config.max_rpm:
                # Превышен лимит - освобождаем slot и ждём
                self.redis.srem(sem_key, slot_id)
                self.redis.delete(slot_ttl_key)
                self.redis.zrem(counter_key, f"{now}:{slot_id}")

                time.sleep(1.0)
                continue

            # Успешно получили разрешение
            wait_time = time.time() - start_time
            logger.debug(
                f"RateLimiter: acquired {engine}/{key} "
                f"(concurrent={current + 1}/{config.max_concurrent}, "
                f"rpm={count}/{config.max_rpm}, wait={wait_time:.2f}s)"
            )

            return AcquireResult(
                success=True,
                wait_time=wait_time,
                slot_id=slot_id,
            )

    def _acquire_local(self, timeout: float) -> AcquireResult:
        """Fallback на локальный семафор при недоступности Redis"""
        with self._local_lock:
            if self._local_sem is None:
                self._local_sem = threading.Semaphore(5)

        start_time = time.time()
        if self._local_sem.acquire(timeout=timeout):
            return AcquireResult(
                success=True,
                wait_time=time.time() - start_time,
                slot_id="local",
            )
        return AcquireResult(
            success=False,
            wait_time=timeout,
            retry_after=5.0,
        )

    def _cleanup_expired_slots(self, engine: str) -> None:
        """Очистка истёкших слотов (защита от deadlock)"""
        sem_key = f"{self.KEY_SEMAPHORE}:{engine}"
        slots = self.redis.smembers(sem_key)

        for slot_id in slots:
            slot_ttl_key = f"{sem_key}:slot:{slot_id}"
            if not self.redis.exists(slot_ttl_key):
                # TTL истёк, удаляем слот
                self.redis.srem(sem_key, slot_id)
                logger.debug(f"Cleaned up expired slot: {slot_id}")

    def release(
        self,
        engine: str,
        key: str = "global",
        slot_id: Optional[str] = None,
    ) -> None:
        """Освободить слот после завершения запроса"""
        if not slot_id:
            return

        if slot_id == "local":
            # Local fallback
            if self._local_sem:
                try:
                    self._local_sem.release()
                except ValueError:
                    pass
            return

        try:
            sem_key = f"{self.KEY_SEMAPHORE}:{engine}"
            slot_ttl_key = f"{sem_key}:slot:{slot_id}"

            pipe = self.redis.pipeline()
            pipe.srem(sem_key, slot_id)
            pipe.delete(slot_ttl_key)
            pipe.execute()

            logger.debug(f"RateLimiter: released {engine}/{key}")
        except Exception as e:
            logger.warning(f"Failed to release slot: {e}")

    def report_429(
        self,
        engine: str,
        retry_after: Optional[int] = None,
    ) -> None:
        """Сообщить о получении 429 от API"""
        try:
            backoff_key = f"{self.KEY_BACKOFF}:{engine}"

            # Получаем текущий backoff или устанавливаем начальный
            current = self.redis.get(backoff_key)
            if current:
                # Увеличиваем backoff экспоненциально
                remaining = float(current) - time.time()
                if remaining > 0:
                    backoff_time = min(self.backoff_max, remaining * 2 + self.backoff_base)
                else:
                    backoff_time = self.backoff_base
            else:
                backoff_time = retry_after or self.backoff_base

            backoff_time = min(backoff_time, self.backoff_max)
            backoff_until = time.time() + backoff_time
            self.redis.setex(backoff_key, int(backoff_time) + 5, str(backoff_until))

            logger.warning(
                f"RateLimiter: 429 received for {engine}, " f"backoff for {backoff_time:.1f}s"
            )
        except Exception as e:
            logger.warning(f"Failed to set backoff: {e}")

    def get_status(self, engine: str) -> RateLimiterStatus:
        """Получить текущий статус rate limiter"""
        try:
            config = self._get_config(engine)
            sem_key = f"{self.KEY_SEMAPHORE}:{engine}"
            counter_key = f"{self.KEY_COUNTER}:{engine}:global"
            backoff_key = f"{self.KEY_BACKOFF}:{engine}"

            now = time.time()
            window_start = now - config.window_seconds

            pipe = self.redis.pipeline()
            pipe.scard(sem_key)
            pipe.zcount(counter_key, window_start, "+inf")
            pipe.get(backoff_key)
            results = pipe.execute()

            backoff_until = float(results[2]) if results[2] else None

            return RateLimiterStatus(
                engine=engine,
                current_concurrent=results[0],
                max_concurrent=config.max_concurrent,
                requests_in_window=results[1],
                max_requests_per_window=config.max_rpm,
                backoff_until=backoff_until if backoff_until and backoff_until > now else None,
            )
        except Exception as e:
            logger.warning(f"Failed to get status: {e}")
            config = self._get_config(engine)
            return RateLimiterStatus(
                engine=engine,
                current_concurrent=0,
                max_concurrent=config.max_concurrent,
                requests_in_window=0,
                max_requests_per_window=config.max_rpm,
            )

    def get_all_status(self) -> dict[str, RateLimiterStatus]:
        """Получить статус всех движков"""
        return {engine: self.get_status(engine) for engine in self.configs.keys()}


# Singleton для глобального доступа
_global_redis_limiter: Optional[RedisRateLimiter] = None
_limiter_lock = threading.Lock()


def get_redis_rate_limiter() -> RedisRateLimiter:
    """Получить глобальный Redis rate limiter"""
    global _global_redis_limiter

    if _global_redis_limiter is None:
        with _limiter_lock:
            if _global_redis_limiter is None:
                from .settings import settings

                engine_configs = {
                    "datalab": EngineConfig(
                        max_rpm=settings.rate_limit_datalab_rpm,
                        max_concurrent=settings.rate_limit_datalab_concurrent,
                    ),
                    "openrouter": EngineConfig(
                        max_rpm=settings.rate_limit_openrouter_rpm,
                        max_concurrent=settings.rate_limit_openrouter_concurrent,
                    ),
                    "client": EngineConfig(
                        max_rpm=settings.rate_limit_client_rpm,
                        max_concurrent=settings.rate_limit_client_concurrent,
                    ),
                    "global": EngineConfig(
                        max_rpm=500,
                        max_concurrent=20,
                    ),
                }

                _global_redis_limiter = RedisRateLimiter(
                    redis_url=settings.redis_url,
                    engine_configs=engine_configs,
                    backoff_base=settings.rate_limit_backoff_base,
                    backoff_max=settings.rate_limit_backoff_max,
                )
                logger.info("Redis rate limiter initialized")

    return _global_redis_limiter


def reset_redis_rate_limiter() -> None:
    """Сбросить глобальный rate limiter (для тестов)"""
    global _global_redis_limiter
    with _limiter_lock:
        _global_redis_limiter = None
