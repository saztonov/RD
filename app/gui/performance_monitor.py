"""Монитор производительности для диагностики подвисаний"""
import logging
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """Монитор производительности UI операций"""
    
    def __init__(self):
        self.enabled = False  # Включить через настройки для отладки
        self._last_operation_time = 0
    
    @contextmanager
    def measure(self, operation_name: str, warn_threshold_ms: float = 16.0):
        """
        Измерить время выполнения операции
        
        Args:
            operation_name: Название операции
            warn_threshold_ms: Порог предупреждения в миллисекундах (по умолчанию 16ms = 60fps)
        """
        if not self.enabled:
            yield
            return
        
        start_time = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start_time) * 1000  # в миллисекундах
            
            if elapsed > warn_threshold_ms:
                logger.warning(
                    f"⚠️ Медленная операция: {operation_name} заняла {elapsed:.2f}ms "
                    f"(порог: {warn_threshold_ms}ms)"
                )
            elif elapsed > 5:  # Логируем все операции > 5ms
                logger.debug(f"🕐 {operation_name}: {elapsed:.2f}ms")


# Глобальный экземпляр
_performance_monitor: Optional[PerformanceMonitor] = None


def get_performance_monitor() -> PerformanceMonitor:
    """Получить глобальный монитор производительности"""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor


def enable_performance_monitoring():
    """Включить мониторинг производительности"""
    monitor = get_performance_monitor()
    monitor.enabled = True
    logger.info("✅ Мониторинг производительности включен")


def disable_performance_monitoring():
    """Выключить мониторинг производительности"""
    monitor = get_performance_monitor()
    monitor.enabled = False
    logger.info("❌ Мониторинг производительности выключен")
