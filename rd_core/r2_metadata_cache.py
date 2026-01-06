"""Кэш метаданных R2 для снижения количества API запросов"""
import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class R2MetadataCache:
    """
    LRU кэш метаданных объектов R2 с TTL.

    Кэширует результаты exists() и list_objects_with_metadata()
    для снижения количества запросов к R2.
    """

    def __init__(self, max_size: int = 10000, ttl_seconds: int = 60):
        """
        Args:
            max_size: Максимальное количество записей в кэше
            ttl_seconds: Время жизни записи в секундах
        """
        self._max_size = max_size
        self._ttl = ttl_seconds

        # exists cache: key -> (exists: bool, timestamp: float)
        self._exists_cache: Dict[str, Tuple[bool, float]] = {}

        # list cache: prefix -> (objects: List[dict], timestamp: float)
        self._list_cache: Dict[str, Tuple[List[dict], float]] = {}

        self._lock = threading.Lock()

    def get_exists(self, key: str) -> Optional[bool]:
        """
        Получить результат exists() из кэша.

        Args:
            key: R2 ключ объекта

        Returns:
            True/False если в кэше и не истёк TTL, иначе None
        """
        with self._lock:
            entry = self._exists_cache.get(key)
            if entry is None:
                return None

            exists, timestamp = entry
            if time.time() - timestamp > self._ttl:
                del self._exists_cache[key]
                return None

            return exists

    def set_exists(self, key: str, value: bool) -> None:
        """
        Сохранить результат exists() в кэш.

        Args:
            key: R2 ключ объекта
            value: Существует ли объект
        """
        with self._lock:
            self._ensure_size(self._exists_cache)
            self._exists_cache[key] = (value, time.time())

    def get_list(self, prefix: str) -> Optional[List[dict]]:
        """
        Получить результат list_objects_with_metadata() из кэша.

        Args:
            prefix: Префикс для поиска

        Returns:
            Список объектов если в кэше и не истёк TTL, иначе None
        """
        with self._lock:
            entry = self._list_cache.get(prefix)
            if entry is None:
                return None

            objects, timestamp = entry
            if time.time() - timestamp > self._ttl:
                del self._list_cache[prefix]
                return None

            return objects

    def set_list(self, prefix: str, objects: List[dict]) -> None:
        """
        Сохранить результат list_objects_with_metadata() в кэш.

        Args:
            prefix: Префикс
            objects: Список объектов с метаданными
        """
        with self._lock:
            self._ensure_size(self._list_cache)
            self._list_cache[prefix] = (objects, time.time())

    def invalidate_key(self, key: str) -> None:
        """
        Инвалидировать кэш для конкретного ключа.
        Вызывается при upload/delete.

        Args:
            key: R2 ключ объекта
        """
        with self._lock:
            # Удаляем из exists кэша
            self._exists_cache.pop(key, None)

            # Инвалидируем list кэш для всех префиксов, которые могут содержать этот ключ
            prefixes_to_remove = []
            for prefix in self._list_cache:
                if key.startswith(prefix):
                    prefixes_to_remove.append(prefix)

            for prefix in prefixes_to_remove:
                del self._list_cache[prefix]

            if prefixes_to_remove:
                logger.debug(
                    f"Invalidated {len(prefixes_to_remove)} list cache entries for key: {key}"
                )

    def invalidate_prefix(self, prefix: str) -> None:
        """
        Инвалидировать весь кэш для префикса.

        Args:
            prefix: Префикс для инвалидации
        """
        with self._lock:
            # Удаляем из list кэша
            self._list_cache.pop(prefix, None)

            # Удаляем все ключи с этим префиксом из exists кэша
            keys_to_remove = [k for k in self._exists_cache if k.startswith(prefix)]
            for key in keys_to_remove:
                del self._exists_cache[key]

            if keys_to_remove:
                logger.debug(
                    f"Invalidated {len(keys_to_remove)} exists cache entries for prefix: {prefix}"
                )

    def clear(self) -> None:
        """Очистить весь кэш."""
        with self._lock:
            self._exists_cache.clear()
            self._list_cache.clear()
            logger.debug("R2 metadata cache cleared")

    def _ensure_size(self, cache: dict) -> None:
        """
        Убедиться, что кэш не превышает max_size.
        Удаляет самые старые записи при превышении.
        """
        if len(cache) >= self._max_size:
            # Удаляем 10% самых старых записей
            items = sorted(cache.items(), key=lambda x: x[1][1])
            to_remove = len(cache) // 10 or 1
            for key, _ in items[:to_remove]:
                del cache[key]

    def stats(self) -> dict:
        """
        Получить статистику кэша.

        Returns:
            Dict с количеством записей и их возрастом
        """
        with self._lock:
            now = time.time()
            exists_count = len(self._exists_cache)
            list_count = len(self._list_cache)

            exists_ages = [
                now - ts for _, (_, ts) in self._exists_cache.items()
            ] if self._exists_cache else []
            list_ages = [
                now - ts for _, (_, ts) in self._list_cache.items()
            ] if self._list_cache else []

            return {
                "exists_entries": exists_count,
                "list_entries": list_count,
                "exists_avg_age": sum(exists_ages) / len(exists_ages) if exists_ages else 0,
                "list_avg_age": sum(list_ages) / len(list_ages) if list_ages else 0,
                "ttl_seconds": self._ttl,
                "max_size": self._max_size,
            }


# Глобальный экземпляр кэша (синглтон)
_cache_instance: Optional[R2MetadataCache] = None
_cache_lock = threading.Lock()


def get_metadata_cache() -> R2MetadataCache:
    """
    Получить глобальный экземпляр кэша метаданных.

    Returns:
        R2MetadataCache instance
    """
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = R2MetadataCache()
    return _cache_instance
