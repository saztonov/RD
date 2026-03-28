"""Circuit breaker для внешних сервисов (LM Studio, Datalab API).

Предотвращает бесполезные запросы к недоступному сервису:
- CLOSED: запросы проходят нормально
- OPEN: запросы блокируются, сервис недоступен
- HALF_OPEN: один пробный запрос для проверки восстановления

Использование:
    breaker = get_circuit_breaker("lmstudio")
    if not breaker.allow_request():
        raise CircuitOpenError("LM Studio unavailable")
    try:
        result = call_lmstudio(...)
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        raise
"""
from __future__ import annotations

import logging
import threading
import time
from enum import Enum, auto

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is blocked."""

    def __init__(self, service: str, retry_after: float = 0):
        self.service = service
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker OPEN for {service}, retry after {retry_after:.0f}s")


class CircuitBreaker:
    """Thread-safe circuit breaker."""

    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._get_state()

    def allow_request(self) -> bool:
        """Check if request should be allowed through."""
        with self._lock:
            state = self._get_state()

            if state == CircuitState.CLOSED:
                return True

            if state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

            # OPEN
            return False

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                logger.info(
                    f"Circuit breaker [{self.service_name}]: CLOSED (success after recovery)",
                    extra={"event": "circuit_closed", "service": self.service_name},
                )
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
                logger.warning(
                    f"Circuit breaker [{self.service_name}]: OPEN (half-open probe failed)",
                    extra={"event": "circuit_open", "service": self.service_name},
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker [{self.service_name}]: OPEN "
                    f"(failures={self._failure_count}/{self.failure_threshold})",
                    extra={"event": "circuit_open", "service": self.service_name},
                )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0

    def _get_state(self) -> CircuitState:
        """Get current state, transitioning OPEN→HALF_OPEN if recovery timeout elapsed."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(
                    f"Circuit breaker [{self.service_name}]: HALF_OPEN "
                    f"(recovery timeout {self.recovery_timeout}s elapsed)",
                    extra={"event": "circuit_half_open", "service": self.service_name},
                )
        return self._state


# ── Global instances ─────────────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_circuit_breaker(
    service: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """Get or create a circuit breaker for a service."""
    with _breakers_lock:
        if service not in _breakers:
            _breakers[service] = CircuitBreaker(
                service_name=service,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return _breakers[service]
