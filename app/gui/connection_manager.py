"""
Менеджер соединения для обработки сетевых ошибок
Позволяет работать офлайн и синхронизировать изменения при восстановлении
"""
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)


class ConnectionStatus(Enum):
    """Статус соединения"""
    CHECKING = "checking"  # Начальная проверка
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


@dataclass
class ConnectionInfo:
    """Информация о соединении"""
    status: ConnectionStatus
    last_check: Optional[datetime] = None
    error_message: Optional[str] = None
    consecutive_failures: int = 0


class ConnectionManager(QObject):
    """
    Менеджер соединения для отслеживания доступности сети
    
    Сигналы:
        - connection_lost: соединение потеряно
        - connection_restored: соединение восстановлено
        - status_changed: статус изменился (ConnectionStatus)
    """
    
    connection_lost = Signal()
    connection_restored = Signal()
    status_changed = Signal(ConnectionStatus)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._info = ConnectionInfo(status=ConnectionStatus.CHECKING)
        self._check_callback: Optional[Callable[[], bool]] = None
        self._check_interval = 15000  # 15 сек
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_connection)
        self._lock = threading.Lock()
        self._first_check_done = False  # Флаг первой проверки
        
    def set_check_callback(self, callback: Callable[[], bool]):
        """
        Установить callback для проверки соединения
        
        Args:
            callback: функция, возвращающая True если соединение доступно
        """
        self._check_callback = callback
        
    def start_monitoring(self):
        """Запустить мониторинг соединения"""
        logger.info("ConnectionManager: начат мониторинг соединения")
        self._check_timer.start(self._check_interval)
        # Первая проверка сразу
        self._check_connection()
        
    def stop_monitoring(self):
        """Остановить мониторинг соединения"""
        logger.info("ConnectionManager: остановлен мониторинг соединения")
        self._check_timer.stop()
        
    def _check_connection(self):
        """Проверить соединение"""
        if not self._check_callback:
            return

        try:
            is_connected = self._check_callback()

            with self._lock:
                old_status = self._info.status
                self._info.last_check = datetime.now()
                is_first_check = not self._first_check_done
                self._first_check_done = True

                if is_connected:
                    # Соединение доступно
                    if old_status != ConnectionStatus.CONNECTED:
                        self._info.status = ConnectionStatus.CONNECTED
                        self._info.consecutive_failures = 0
                        self._info.error_message = None
                        logger.info("ConnectionManager: соединение установлено")
                        self.status_changed.emit(ConnectionStatus.CONNECTED)
                        # При первой проверке не emit connection_restored (не было потери)
                        if not is_first_check:
                            self.connection_restored.emit()
                    else:
                        self._info.consecutive_failures = 0
                else:
                    # Соединение недоступно
                    self._info.consecutive_failures += 1

                    if old_status in (ConnectionStatus.CONNECTED, ConnectionStatus.CHECKING):
                        self._info.status = ConnectionStatus.DISCONNECTED
                        self._info.error_message = "Нет подключения к интернету"
                        logger.warning("ConnectionManager: нет соединения")
                        self.status_changed.emit(ConnectionStatus.DISCONNECTED)
                        # При первой проверке не emit connection_lost
                        if not is_first_check:
                            self.connection_lost.emit()
                    elif old_status == ConnectionStatus.DISCONNECTED:
                        # Пытаемся переподключиться
                        if self._info.consecutive_failures % 3 == 0:
                            self._info.status = ConnectionStatus.RECONNECTING
                            logger.info("ConnectionManager: попытка переподключения...")
                            self.status_changed.emit(ConnectionStatus.RECONNECTING)

        except Exception as e:
            logger.error(f"ConnectionManager: ошибка проверки соединения: {e}")
            
    def get_status(self) -> ConnectionStatus:
        """Получить текущий статус соединения"""
        with self._lock:
            return self._info.status
            
    def is_connected(self) -> bool:
        """Проверить доступность соединения"""
        with self._lock:
            return self._info.status == ConnectionStatus.CONNECTED
            
    def get_error_message(self) -> Optional[str]:
        """Получить сообщение об ошибке"""
        with self._lock:
            return self._info.error_message
            
    def mark_error(self, error_message: str):
        """
        Пометить ошибку соединения вручную
        
        Args:
            error_message: сообщение об ошибке
        """
        with self._lock:
            if self._info.status == ConnectionStatus.CONNECTED:
                self._info.status = ConnectionStatus.DISCONNECTED
                self._info.error_message = error_message
                self._info.consecutive_failures = 1
                logger.warning(f"ConnectionManager: ошибка соединения: {error_message}")
                self.status_changed.emit(ConnectionStatus.DISCONNECTED)
                self.connection_lost.emit()


def is_network_error(exception: Exception) -> bool:
    """
    Проверить является ли исключение сетевой ошибкой
    
    Args:
        exception: исключение
        
    Returns:
        True если это сетевая ошибка
    """
    import httpx
    import socket
    from requests.exceptions import ConnectionError, Timeout
    from urllib3.exceptions import MaxRetryError, NewConnectionError
    
    network_exceptions = (
        # httpx
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.RemoteProtocolError,
        # requests
        ConnectionError,
        Timeout,
        # urllib3
        MaxRetryError,
        NewConnectionError,
        # socket
        socket.timeout,
        socket.gaierror,
        ConnectionRefusedError,
        ConnectionResetError,
    )
    
    return isinstance(exception, network_exceptions)


def handle_network_error(func):
    """
    Декоратор для обработки сетевых ошибок
    
    Возвращает None при сетевой ошибке вместо выброса исключения
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if is_network_error(e):
                logger.warning(f"Сетевая ошибка в {func.__name__}: {e}")
                return None
            raise
    return wrapper
