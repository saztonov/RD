"""Тесты для _wait_for_backend — учёт deadline задачи.

Регрессия: в продакшн-логе 2026-04-28 функция вызывалась с max_wait=300с,
хотя до Celery soft_time_limit оставалось 142с. time.sleep(15) попадал
в SoftTimeLimitExceeded, traceback всплывал, верификация падала.
"""

import time
from unittest.mock import MagicMock, patch

from services.remote_ocr.server.block_verification import _wait_for_backend


class ChandraBackend:
    """Fake-класс с именем 'ChandraBackend' для прохождения _is_lmstudio_backend."""

    def __init__(self, available: bool):
        self.base_url = "https://example.invalid"
        self.session = MagicMock()
        self.session.get.return_value.status_code = 200 if available else 503


def test_returns_true_immediately_if_backend_available():
    backend = ChandraBackend(available=True)
    assert _wait_for_backend(backend, max_wait=300) is True


def test_returns_false_if_deadline_already_past():
    """deadline в прошлом — функция должна вернуть False сразу, БЕЗ time.sleep."""
    backend = ChandraBackend(available=False)
    past_deadline = time.time() - 100  # 100с в прошлом

    with patch("services.remote_ocr.server.block_verification.time.sleep") as mock_sleep:
        result = _wait_for_backend(
            backend, max_wait=300, check_interval=15, deadline=past_deadline
        )

    assert result is False
    mock_sleep.assert_not_called(), (
        "При истёкшем deadline функция не должна вызывать time.sleep"
    )


def test_deadline_caps_sleep_duration():
    """deadline через 8с — sleep не должен быть длиннее ~3с (8 - 5 reserve)."""
    backend = ChandraBackend(available=False)
    deadline = time.time() + 8

    sleep_calls = []
    with patch(
        "services.remote_ocr.server.block_verification.time.sleep",
        side_effect=lambda s: sleep_calls.append(s),
    ):
        _wait_for_backend(
            backend, max_wait=300, check_interval=15, deadline=deadline
        )

    # Хотя бы один sleep должен быть, и он не должен превышать deadline-reserve (~3с)
    assert sleep_calls, "Ожидался хотя бы один time.sleep"
    assert max(sleep_calls) <= 4, (
        f"Sleep не должен превышать deadline-reserve, был {max(sleep_calls)}"
    )


def test_no_deadline_uses_check_interval():
    """Без deadline функция спит full check_interval."""
    backend = ChandraBackend(available=False)
    sleep_calls = []

    with patch(
        "services.remote_ocr.server.block_verification.time.sleep",
        side_effect=lambda s: sleep_calls.append(s),
    ):
        _wait_for_backend(backend, max_wait=30, check_interval=15, deadline=None)

    assert sleep_calls, "Ожидался хотя бы один sleep"
    assert all(s <= 15.001 for s in sleep_calls)
