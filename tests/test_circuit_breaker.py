"""Тесты для circuit breaker."""
import time

import pytest

from services.remote_ocr.server.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


@pytest.fixture
def breaker():
    return CircuitBreaker("test_service", failure_threshold=3, recovery_timeout=0.2)


class TestCircuitBreakerStates:
    def test_initial_state_is_closed(self, breaker):
        assert breaker.state == CircuitState.CLOSED

    def test_allows_requests_when_closed(self, breaker):
        assert breaker.allow_request() is True

    def test_stays_closed_below_threshold(self, breaker):
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request() is True

    def test_opens_at_threshold(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_blocks_requests_when_open(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        assert breaker.allow_request() is False

    def test_transitions_to_half_open_after_timeout(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.25)
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_allows_one_probe(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        time.sleep(0.25)

        assert breaker.allow_request() is True  # probe
        assert breaker.allow_request() is False  # blocked

    def test_success_after_half_open_closes(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        time.sleep(0.25)

        breaker.allow_request()  # probe
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request() is True

    def test_failure_in_half_open_reopens(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        time.sleep(0.25)

        breaker.allow_request()  # probe
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_success_resets_failure_count(self, breaker):
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        # After reset, need 3 more failures to open
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

    def test_reset_clears_state(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request() is True


class TestCircuitOpenError:
    def test_error_attributes(self):
        err = CircuitOpenError("lmstudio", retry_after=60)
        assert err.service == "lmstudio"
        assert err.retry_after == 60
        assert "lmstudio" in str(err)
