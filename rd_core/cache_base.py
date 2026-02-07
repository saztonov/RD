"""Базовые классы для кэширования с потокобезопасностью"""
import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ThreadSafeCache(ABC, Generic[T]):
    """
    Базовый класс для потокобезопасного in-memory кэша с TTL.

    Предоставляет:
    - Потокобезопасный доступ через Lock
    - TTL-based инвалидацию
    - LRU eviction при превышении max_size
    """

    def __init__(self, max_size: int = 10000, ttl_seconds: int = 60):
        """
        Args:
            max_size: Максимальное количество записей
            ttl_seconds: Время жизни записи в секундах (0 = без TTL)
        """
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    @property
    def lock(self) -> threading.Lock:
        """Доступ к lock для подклассов"""
        return self._lock

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def ttl(self) -> int:
        return self._ttl

    def is_expired(self, timestamp: float) -> bool:
        """Проверить, истёк ли TTL для записи"""
        if self._ttl <= 0:
            return False
        return time.time() - timestamp > self._ttl

    def ensure_size(self, cache: Dict[str, tuple], max_count: Optional[int] = None) -> None:
        """
        Убедиться, что кэш не превышает max_size.
        Удаляет самые старые записи (LRU) при превышении.

        ВАЖНО: Вызывать внутри блока with self._lock!

        Args:
            cache: Словарь кэша где value = (data, timestamp)
            max_count: Опциональный лимит (по умолчанию self._max_size)
        """
        limit = max_count if max_count is not None else self._max_size
        if len(cache) < limit:
            return

        # Удаляем 10% самых старых записей
        items = sorted(cache.items(), key=lambda x: x[1][-1])  # Сортируем по timestamp (последний элемент tuple)
        to_remove = len(cache) // 10 or 1
        for key, _ in items[:to_remove]:
            del cache[key]

    @abstractmethod
    def clear(self) -> None:
        """Очистить весь кэш"""
        pass

    @abstractmethod
    def stats(self) -> dict:
        """Получить статистику кэша"""
        pass


class PersistentCacheIndex:
    """
    Миксин для кэшей с персистентным индексом на диске.

    Предоставляет:
    - Атомарную загрузку/сохранение индекса
    - Версионирование формата
    """

    def __init__(self, index_file: Path):
        """
        Args:
            index_file: Путь к файлу индекса
        """
        self._index_file = index_file
        self._index_file.parent.mkdir(parents=True, exist_ok=True)

    def load_index(self) -> Optional[dict]:
        """
        Загрузить индекс с диска.

        Returns:
            Dict с данными или None если файл не существует/ошибка
        """
        if not self._index_file.exists():
            return None

        try:
            with open(self._index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.debug(f"Cache index loaded from {self._index_file}")
            return data
        except Exception as e:
            logger.warning(f"Failed to load cache index: {e}")
            return None

    def save_index(self, data: dict) -> bool:
        """
        Сохранить индекс на диск (атомарно через temp file).

        Args:
            data: Данные для сохранения

        Returns:
            True если успешно
        """
        try:
            temp_file = self._index_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self._index_file)
            return True
        except Exception as e:
            logger.warning(f"Failed to save cache index: {e}")
            return False
