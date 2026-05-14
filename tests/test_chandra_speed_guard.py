"""Тесты для Chandra Speed Guard — авто-перезагрузка модели при деградации.

Покрытие:
- Slow-counter (record/reset/get) и in-flight counter.
- Lock + cooldown + pause-flag.
- Детект чужих моделей в LM Studio (list_loaded_lmstudio_models, has_foreign_loaded_model).
- perform_full_lmstudio_reload: выгружает ВСЕ instance всех моделей (включая chandra),
  затем грузит chandra-ocr-2 заново.
- try_speed_guard_reload: уважает cooldown, exclusive lock.
- ChandraBackend.recognize: записывает slow-sample при таймауте/медленном ответе,
  сбрасывает счётчик при быстром успехе, триггерит reload при достижении порога.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# ── In-memory Redis stub ────────────────────────────────────────────


class _FakeRedis:
    """Минимальный in-memory Redis-стаб (только нужные команды)."""

    def __init__(self):
        self._data: dict = {}
        self._sets: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            return self._data.get(key)

    def set(self, key, value, ex=None, nx=False):
        with self._lock:
            if nx and key in self._data:
                return False
            self._data[key] = str(value)
            return True

    def delete(self, *keys):
        with self._lock:
            removed = 0
            for k in keys:
                if k in self._data:
                    del self._data[k]
                    removed += 1
                if k in self._sets:
                    del self._sets[k]
                    removed += 1
            return removed

    def exists(self, key):
        with self._lock:
            return 1 if (key in self._data or key in self._sets) else 0

    def expire(self, key, ttl):
        return True

    def incr(self, key):
        with self._lock:
            new_val = int(self._data.get(key, 0)) + 1
            self._data[key] = str(new_val)
            return new_val

    def decr(self, key):
        with self._lock:
            new_val = int(self._data.get(key, 0)) - 1
            self._data[key] = str(new_val)
            return new_val

    def sadd(self, key, *members):
        with self._lock:
            s = self._sets.setdefault(key, set())
            added = 0
            for m in members:
                if m not in s:
                    s.add(m)
                    added += 1
            return added

    def srem(self, key, *members):
        with self._lock:
            s = self._sets.get(key)
            if not s:
                return 0
            removed = 0
            for m in members:
                if m in s:
                    s.remove(m)
                    removed += 1
            return removed

    def scard(self, key):
        with self._lock:
            return len(self._sets.get(key, set()))


@pytest.fixture
def fake_redis(monkeypatch):
    """Подменяет _get_redis_client в lmstudio_lifecycle на in-memory стаб."""
    from services.remote_ocr.server import lmstudio_lifecycle

    stub = _FakeRedis()
    monkeypatch.setattr(lmstudio_lifecycle, "_get_redis_client", lambda: stub)
    return stub


@pytest.fixture
def speed_guard_settings(monkeypatch):
    """Включает speed_guard и задаёт короткие таймауты для тестов."""
    from services.remote_ocr.server import lmstudio_lifecycle

    fake_settings = MagicMock()
    fake_settings.chandra_speed_guard_enabled = True
    fake_settings.chandra_slow_request_seconds = 90
    fake_settings.chandra_slow_consecutive_requests = 3
    fake_settings.chandra_slow_reload_cooldown_seconds = 300
    fake_settings.chandra_speed_guard_drain_timeout = 1
    fake_settings.chandra_speed_guard_lock_ttl = 60
    fake_settings.chandra_base_url = "http://lmstudio.test"
    monkeypatch.setattr(lmstudio_lifecycle, "settings", fake_settings)
    return fake_settings


# ── Counter ─────────────────────────────────────────────────────────


def test_record_slow_sample_increments(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        get_slow_counter,
        record_slow_sample,
    )

    assert get_slow_counter() == 0
    assert record_slow_sample() == 1
    assert record_slow_sample() == 2
    assert record_slow_sample() == 3
    assert get_slow_counter() == 3


def test_reset_slow_counter_clears(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        get_slow_counter,
        record_slow_sample,
        reset_slow_counter,
    )

    record_slow_sample()
    record_slow_sample()
    assert get_slow_counter() == 2
    reset_slow_counter()
    assert get_slow_counter() == 0


def test_inflight_counter_no_negative(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        decr_inflight,
        get_inflight,
        incr_inflight,
    )

    incr_inflight()
    assert get_inflight() == 1
    decr_inflight()
    assert get_inflight() == 0
    decr_inflight()  # под ноль не должно уйти
    assert get_inflight() == 0


# ── Lock / cooldown / pause-flag ────────────────────────────────────


def test_acquire_reload_lock_exclusive(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        acquire_reload_lock,
        release_reload_lock,
    )

    assert acquire_reload_lock(60) is True
    assert acquire_reload_lock(60) is False  # второй вызов не проходит
    release_reload_lock()
    assert acquire_reload_lock(60) is True


def test_cooldown_blocks_after_mark(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        is_in_cooldown,
        mark_reload_completed,
    )

    assert is_in_cooldown(300) is False
    mark_reload_completed()
    assert is_in_cooldown(300) is True
    assert is_in_cooldown(0) is False  # cooldown=0 → никогда не в cooldown


def test_pause_flag_lifecycle(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        clear_reload_in_progress,
        is_reload_in_progress,
        set_reload_in_progress,
    )

    assert is_reload_in_progress() is False
    set_reload_in_progress(60)
    assert is_reload_in_progress() is True
    clear_reload_in_progress()
    assert is_reload_in_progress() is False


# ── Детект чужих моделей ────────────────────────────────────────────


def test_has_foreign_loaded_model_true():
    from services.remote_ocr.server.lmstudio_lifecycle import has_foreign_loaded_model

    loaded = [
        {"key": "chandra-ocr-2", "instances": ["i1"]},
        {"key": "google/gemma-3", "instances": ["i2"]},
    ]
    assert has_foreign_loaded_model(loaded) is True


def test_has_foreign_loaded_model_false_only_chandra():
    from services.remote_ocr.server.lmstudio_lifecycle import has_foreign_loaded_model

    loaded = [{"key": "chandra-ocr-2", "instances": ["i1"]}]
    assert has_foreign_loaded_model(loaded) is False


def test_has_foreign_loaded_model_false_empty():
    from services.remote_ocr.server.lmstudio_lifecycle import has_foreign_loaded_model

    assert has_foreign_loaded_model([]) is False


def test_list_loaded_lmstudio_models_filters_empty_instances(monkeypatch):
    from services.remote_ocr.server import lmstudio_lifecycle

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "models": [
            {"key": "chandra-ocr-2", "loaded_instances": [{"id": "i1"}, {"id": "i2"}]},
            {"key": "google/gemma-3", "loaded_instances": []},  # не загружена
            {"key": "qwen-vl", "loaded_instances": [{"id": "i3"}]},
        ]
    }
    monkeypatch.setattr(
        lmstudio_lifecycle.__name__.rsplit(".", 1)[0] + ".lmstudio_lifecycle",
        lmstudio_lifecycle,
        raising=False,
    )
    with patch("requests.get", return_value=fake_resp):
        loaded = lmstudio_lifecycle.list_loaded_lmstudio_models("http://lmstudio.test")

    keys = {entry["key"] for entry in loaded}
    assert keys == {"chandra-ocr-2", "qwen-vl"}
    chandra = next(e for e in loaded if e["key"] == "chandra-ocr-2")
    assert sorted(chandra["instances"]) == ["i1", "i2"]


def test_list_loaded_lmstudio_models_handles_http_error():
    from services.remote_ocr.server.lmstudio_lifecycle import list_loaded_lmstudio_models

    fake_resp = MagicMock(status_code=500, text="boom")
    with patch("requests.get", return_value=fake_resp):
        assert list_loaded_lmstudio_models("http://lmstudio.test") == []


# ── Drain ───────────────────────────────────────────────────────────


def test_wait_for_inflight_drain_returns_true_when_empty(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import wait_for_inflight_drain

    assert wait_for_inflight_drain(timeout_seconds=1) is True


def test_wait_for_inflight_drain_waits_for_decr(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        decr_inflight,
        incr_inflight,
        wait_for_inflight_drain,
    )

    incr_inflight()

    def _decr_later():
        time.sleep(0.6)
        decr_inflight()

    t = threading.Thread(target=_decr_later, daemon=True)
    t.start()
    assert wait_for_inflight_drain(timeout_seconds=3) is True
    t.join()


def test_wait_for_inflight_drain_timeout(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        incr_inflight,
        wait_for_inflight_drain,
    )

    incr_inflight()
    assert wait_for_inflight_drain(timeout_seconds=1) is False


# ── perform_full_lmstudio_reload ────────────────────────────────────


def test_perform_full_reload_unloads_all_loaded_models(fake_redis):
    """Должно вызвать POST /unload для КАЖДОГО instance каждой загруженной модели."""
    from services.remote_ocr.server.lmstudio_lifecycle import perform_full_lmstudio_reload

    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {
        "models": [
            {"key": "chandra-ocr-2", "loaded_instances": [{"id": "ch-1"}, {"id": "ch-2"}]},
            {"key": "google/gemma-3", "loaded_instances": [{"id": "gm-1"}]},
        ]
    }
    unload_resp = MagicMock(status_code=200)
    load_resp = MagicMock(status_code=200)
    load_resp.json.return_value = {"load_config": {"context_length": 36601}, "load_time_seconds": 5}

    posted_payloads = []

    def _post(url, **kwargs):
        posted_payloads.append((url, kwargs.get("json")))
        if "/unload" in url:
            return unload_resp
        if "/load" in url:
            return load_resp
        return MagicMock(status_code=404)

    with patch("requests.get", return_value=list_resp), patch("requests.post", side_effect=_post):
        ok = perform_full_lmstudio_reload("http://lmstudio.test", reason="test")

    assert ok is True
    unload_calls = [p for url, p in posted_payloads if "/unload" in url]
    unloaded_ids = sorted(p["instance_id"] for p in unload_calls)
    assert unloaded_ids == ["ch-1", "ch-2", "gm-1"]
    load_calls = [p for url, p in posted_payloads if "/load" in url]
    assert len(load_calls) == 1
    assert load_calls[0]["model"] == "chandra-ocr-2"
    # CHANDRA_LOAD_CONFIG передан целиком
    assert load_calls[0]["context_length"] == 36601


def test_perform_full_reload_when_only_chandra_loaded(fake_redis):
    """Если загружена только chandra — всё равно unload+load (требование пользователя)."""
    from services.remote_ocr.server.lmstudio_lifecycle import perform_full_lmstudio_reload

    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {
        "models": [
            {"key": "chandra-ocr-2", "loaded_instances": [{"id": "ch-1"}]},
        ]
    }
    unload_resp = MagicMock(status_code=200)
    load_resp = MagicMock(status_code=200)
    load_resp.json.return_value = {"load_config": {}, "load_time_seconds": 4}

    seen_urls = []

    def _post(url, **kwargs):
        seen_urls.append(url)
        return unload_resp if "/unload" in url else load_resp

    with patch("requests.get", return_value=list_resp), patch("requests.post", side_effect=_post):
        ok = perform_full_lmstudio_reload("http://lmstudio.test", reason="solo_chandra")

    assert ok is True
    assert any("/unload" in u for u in seen_urls)
    assert any("/load" in u for u in seen_urls)


def test_perform_full_reload_marks_cooldown_only_on_success(fake_redis):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        is_in_cooldown,
        perform_full_lmstudio_reload,
    )

    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {"models": []}
    # /load возвращает 500 → reload не удался → cooldown НЕ ставим
    load_resp = MagicMock(status_code=500, text="boom")

    with patch("requests.get", return_value=list_resp), patch("requests.post", return_value=load_resp):
        ok = perform_full_lmstudio_reload("http://lmstudio.test", reason="fail_test")

    assert ok is False
    assert is_in_cooldown(300) is False


# ── try_speed_guard_reload ──────────────────────────────────────────


def test_try_speed_guard_reload_respects_disabled_flag(fake_redis, speed_guard_settings):
    from services.remote_ocr.server.lmstudio_lifecycle import try_speed_guard_reload

    speed_guard_settings.chandra_speed_guard_enabled = False
    with patch(
        "services.remote_ocr.server.lmstudio_lifecycle.perform_full_lmstudio_reload"
    ) as do_reload:
        assert try_speed_guard_reload("http://lmstudio.test", "test") is False
    do_reload.assert_not_called()


def test_try_speed_guard_reload_respects_cooldown(fake_redis, speed_guard_settings):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        mark_reload_completed,
        try_speed_guard_reload,
    )

    mark_reload_completed()  # сразу после reload
    with patch(
        "services.remote_ocr.server.lmstudio_lifecycle.perform_full_lmstudio_reload"
    ) as do_reload:
        assert try_speed_guard_reload("http://lmstudio.test", "test") is False
    do_reload.assert_not_called()


def test_try_speed_guard_reload_only_one_at_a_time(fake_redis, speed_guard_settings):
    """Второй вызов параллельно — должен вернуть False (lock занят)."""
    from services.remote_ocr.server.lmstudio_lifecycle import (
        acquire_reload_lock,
        try_speed_guard_reload,
    )

    # Имитируем "другой воркер уже взял lock"
    assert acquire_reload_lock(60) is True
    with patch(
        "services.remote_ocr.server.lmstudio_lifecycle.perform_full_lmstudio_reload"
    ) as do_reload:
        assert try_speed_guard_reload("http://lmstudio.test", "test") is False
    do_reload.assert_not_called()


def test_try_speed_guard_reload_executes(fake_redis, speed_guard_settings):
    from services.remote_ocr.server.lmstudio_lifecycle import (
        clear_reload_in_progress,
        is_reload_in_progress,
        try_speed_guard_reload,
    )

    clear_reload_in_progress()
    with patch(
        "services.remote_ocr.server.lmstudio_lifecycle.perform_full_lmstudio_reload",
        return_value=True,
    ) as do_reload:
        ok = try_speed_guard_reload("http://lmstudio.test", "slow_streak")

    assert ok is True
    do_reload.assert_called_once_with("http://lmstudio.test", "slow_streak")
    # pause-flag должен быть снят
    assert is_reload_in_progress() is False


# ── ChandraBackend интеграция ────────────────────────────────────────


@pytest.fixture
def fast_chandra_backend(monkeypatch):
    """ChandraBackend без preload/real-HTTP. Подменяет хуки на mock."""
    from rd_core.ocr import chandra as chandra_module
    from rd_core.ocr.chandra import ChandraBackend

    backend = ChandraBackend(base_url="http://lmstudio.test", http_timeout=120)
    backend._model_id = "chandra-ocr-2"

    hooks = MagicMock()
    hooks.settings = MagicMock(
        chandra_speed_guard_enabled=True,
        chandra_slow_request_seconds=90,
        chandra_slow_consecutive_requests=3,
    )
    hooks.is_paused.return_value = False
    hooks.list_loaded.return_value = []
    hooks.has_foreign.return_value = False
    hooks.record_slow.side_effect = [1, 2, 3, 4, 5]
    hooks.reset_slow.return_value = None
    hooks.incr_inflight.return_value = 1
    hooks.decr_inflight.return_value = 0
    hooks.try_reload.return_value = True

    monkeypatch.setattr(chandra_module, "_get_guard_hooks", lambda: hooks)
    return backend, hooks


def test_chandra_records_slow_on_timeout(fast_chandra_backend):
    backend, hooks = fast_chandra_backend
    backend._MAX_APP_RETRIES = 0

    from PIL import Image
    import requests

    img = Image.new("RGB", (10, 10))

    with patch.object(
        backend.session, "post", side_effect=requests.exceptions.Timeout()
    ):
        result = backend.recognize(img)

    # Должен записать slow-sample (по таймауту)
    assert hooks.record_slow.called
    # Триггер reload не сработал (счётчик 1 < threshold 3)
    hooks.try_reload.assert_not_called()
    assert "Ошибка" in result or "таймаут" in result.lower()


def test_chandra_triggers_reload_at_threshold(fast_chandra_backend, monkeypatch):
    backend, hooks = fast_chandra_backend
    backend._MAX_APP_RETRIES = 0
    # 3-й вызов record_slow вернёт 3 → должен сработать триггер
    hooks.record_slow.side_effect = [3]

    from PIL import Image
    import requests

    img = Image.new("RGB", (10, 10))

    with patch.object(
        backend.session, "post", side_effect=requests.exceptions.Timeout()
    ):
        backend.recognize(img)

    hooks.try_reload.assert_called_once()
    args, _ = hooks.try_reload.call_args
    assert args[0] == "http://lmstudio.test"
    assert args[1] == "timeout_streak"


def test_chandra_triggers_reload_on_foreign_model(fast_chandra_backend):
    backend, hooks = fast_chandra_backend
    backend._MAX_APP_RETRIES = 0
    # 1 медленный запрос + чужая модель → мгновенный триггер
    hooks.record_slow.side_effect = [1]
    hooks.list_loaded.return_value = [
        {"key": "chandra-ocr-2", "instances": ["c1"]},
        {"key": "google/gemma-3", "instances": ["g1"]},
    ]
    hooks.has_foreign.return_value = True

    from PIL import Image
    import requests

    img = Image.new("RGB", (10, 10))

    with patch.object(
        backend.session, "post", side_effect=requests.exceptions.Timeout()
    ):
        backend.recognize(img)

    hooks.try_reload.assert_called_once()
    args, _ = hooks.try_reload.call_args
    assert args[1] == "foreign_loaded"


def test_chandra_resets_counter_on_fast_success(fast_chandra_backend):
    backend, hooks = fast_chandra_backend
    backend._MAX_APP_RETRIES = 0

    from PIL import Image

    img = Image.new("RGB", (10, 10))

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "<p>Test OCR</p>"}}],
        "usage": {"completion_tokens": 42},
    }

    with patch.object(backend.session, "post", return_value=fake_response):
        result = backend.recognize(img)

    assert "<p>Test OCR</p>" in result
    hooks.reset_slow.assert_called()
    hooks.try_reload.assert_not_called()


def test_chandra_records_slow_on_slow_success(fast_chandra_backend, monkeypatch):
    """elapsed >= chandra_slow_request_seconds → slow-sample, без timeout."""
    backend, hooks = fast_chandra_backend
    backend._MAX_APP_RETRIES = 0

    from PIL import Image

    img = Image.new("RGB", (10, 10))

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "<p>Slow OCR</p>"}}],
        "usage": {"completion_tokens": 100},
    }

    # Эмулируем медленный запрос через time.monotonic mock
    from rd_core.ocr import chandra as chandra_module

    original_monotonic = chandra_module.time.monotonic
    counter = {"v": 0.0}

    def fake_monotonic():
        counter["v"] += 100.0  # каждый вызов прыжок на 100с
        return counter["v"]

    monkeypatch.setattr(chandra_module.time, "monotonic", fake_monotonic)

    with patch.object(backend.session, "post", return_value=fake_response):
        try:
            backend.recognize(img)
        finally:
            monkeypatch.setattr(chandra_module.time, "monotonic", original_monotonic)

    # Был записан slow-sample (elapsed >> 90с)
    hooks.record_slow.assert_called()
    hooks.reset_slow.assert_not_called()


def test_chandra_force_reload_resets_model_id(fast_chandra_backend):
    backend, hooks = fast_chandra_backend
    backend._model_id = "chandra-ocr-2"
    hooks.try_reload.return_value = True

    ok = backend.force_reload_all_models("manual")
    assert ok is True
    assert backend._model_id is None


def test_chandra_force_reload_keeps_model_id_on_failure(fast_chandra_backend):
    backend, hooks = fast_chandra_backend
    backend._model_id = "chandra-ocr-2"
    hooks.try_reload.return_value = False

    ok = backend.force_reload_all_models("manual")
    assert ok is False
    assert backend._model_id == "chandra-ocr-2"
