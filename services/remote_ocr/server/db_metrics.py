"""Database call metrics tracking per job"""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class JobMetrics:
    """Metrics for a single job"""

    supabase_reads: int = 0
    supabase_writes: int = 0
    redis_reads: int = 0
    redis_writes: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def to_dict(self) -> Dict[str, Any]:
        total_cache = self.cache_hits + self.cache_misses
        return {
            "supabase_reads": self.supabase_reads,
            "supabase_writes": self.supabase_writes,
            "supabase_total": self.supabase_reads + self.supabase_writes,
            "redis_reads": self.redis_reads,
            "redis_writes": self.redis_writes,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(100 * self.cache_hits / total_cache, 1) if total_cache > 0 else 0,
        }


class DBMetricsCollector:
    """Thread-safe metrics collector for database operations"""

    def __init__(self):
        self._metrics: Dict[str, JobMetrics] = defaultdict(JobMetrics)
        self._lock = threading.Lock()

    def record_supabase_read(self, job_id: str, count: int = 1) -> None:
        with self._lock:
            self._metrics[job_id].supabase_reads += count

    def record_supabase_write(self, job_id: str, count: int = 1) -> None:
        with self._lock:
            self._metrics[job_id].supabase_writes += count

    def record_redis_read(self, job_id: str, count: int = 1) -> None:
        with self._lock:
            self._metrics[job_id].redis_reads += count

    def record_redis_write(self, job_id: str, count: int = 1) -> None:
        with self._lock:
            self._metrics[job_id].redis_writes += count

    def record_cache_hit(self, job_id: str) -> None:
        with self._lock:
            self._metrics[job_id].cache_hits += 1

    def record_cache_miss(self, job_id: str) -> None:
        with self._lock:
            self._metrics[job_id].cache_misses += 1

    def get_metrics(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if job_id in self._metrics:
                return self._metrics[job_id].to_dict()
        return None

    def pop_metrics(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get and remove metrics for a job"""
        with self._lock:
            if job_id in self._metrics:
                metrics = self._metrics.pop(job_id)
                return metrics.to_dict()
        return None

    def log_summary(self, job_id: str) -> None:
        """Log metrics summary for a job"""
        metrics = self.get_metrics(job_id)
        if metrics:
            logger.info(
                f"[DB_METRICS] Job {job_id}: "
                f"Supabase R/W: {metrics['supabase_reads']}/{metrics['supabase_writes']}, "
                f"Redis R/W: {metrics['redis_reads']}/{metrics['redis_writes']}, "
                f"Cache hit rate: {metrics['cache_hit_rate']}%"
            )


_collector: Optional[DBMetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> DBMetricsCollector:
    """Get global metrics collector (singleton)"""
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = DBMetricsCollector()
    return _collector
