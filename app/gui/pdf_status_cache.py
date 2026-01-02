"""Кеш статусов PDF документов"""
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PDFStatusCacheEntry:
    """Запись в кеше статуса PDF"""
    status: str
    message: str
    timestamp: float


class PDFStatusCache:
    """Кеш статусов PDF документов с TTL"""
    
    def __init__(self, ttl_seconds: int = 300):
        """
        Args:
            ttl_seconds: Время жизни записи в кеше (по умолчанию 5 минут)
        """
        self._cache: Dict[str, PDFStatusCacheEntry] = {}
        self._ttl = ttl_seconds
    
    def get(self, node_id: str) -> Optional[Tuple[str, str]]:
        """
        Получить статус из кеша
        
        Returns:
            Tuple (status, message) или None если нет в кеше или истёк TTL
        """
        entry = self._cache.get(node_id)
        if not entry:
            return None
        
        # Проверяем TTL
        if time.time() - entry.timestamp > self._ttl:
            # Истёк - удаляем
            del self._cache[node_id]
            return None
        
        return entry.status, entry.message
    
    def set(self, node_id: str, status: str, message: str):
        """Сохранить статус в кеш"""
        self._cache[node_id] = PDFStatusCacheEntry(
            status=status,
            message=message,
            timestamp=time.time()
        )
        logger.debug(f"Cached PDF status for {node_id}: {status}")
    
    def invalidate(self, node_id: str):
        """Инвалидировать статус для конкретного узла"""
        if node_id in self._cache:
            del self._cache[node_id]
            logger.debug(f"Invalidated PDF status cache for {node_id}")
    
    def invalidate_all(self):
        """Очистить весь кеш"""
        count = len(self._cache)
        self._cache.clear()
        logger.debug(f"Invalidated all PDF status cache ({count} entries)")
    
    def get_cached_count(self) -> int:
        """Получить количество закешированных записей"""
        return len(self._cache)
    
    def cleanup_expired(self):
        """Удалить истёкшие записи"""
        current_time = time.time()
        expired_keys = [
            node_id for node_id, entry in self._cache.items()
            if current_time - entry.timestamp > self._ttl
        ]
        
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired PDF status entries")
        
        return len(expired_keys)


# Глобальный экземпляр кеша
_pdf_status_cache = None


def get_pdf_status_cache() -> PDFStatusCache:
    """Получить глобальный экземпляр кеша статусов PDF"""
    global _pdf_status_cache
    if _pdf_status_cache is None:
        _pdf_status_cache = PDFStatusCache(ttl_seconds=300)  # 5 минут
    return _pdf_status_cache
