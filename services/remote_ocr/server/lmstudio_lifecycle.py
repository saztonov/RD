"""Управление lifecycle моделей LM Studio при параллельных Celery задачах.

Delayed unload: вместо немедленной выгрузки при remaining==0,
модель остаётся загруженной на UNLOAD_GRACE_SECONDS. Если за это время
придёт новая задача — выгрузка отменяется (acquire удаляет pending ключ).

Celery prefork = отдельные процессы. Каждый создаёт Backend
и вызывает unload_model() в finally. Redis SET координирует
выгрузку: модель выгружается только когда последняя задача завершится.

Используется Redis SET (SADD/SREM/SCARD) вместо INCR/DECR:
- SET не может уйти в минус
- Не допускает дублей (повторный acquire одного job_id — no-op)
- release без acquire — безопасный no-op (SREM несуществующего элемента)
- TTL 24h как страховка от крашей

Поддерживает движок chandra через параметрический ключ.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import redis

from .logging_config import get_logger
from .settings import settings

logger = get_logger(__name__)

_redis_pool: redis.ConnectionPool | None = None
_pool_lock = threading.Lock()

# TTL для SET-ключа — страховка от крашей (24 часа)
_SAFETY_TTL = 86400

# Grace period перед выгрузкой модели (секунды)
UNLOAD_GRACE_SECONDS = 120


def _active_key(engine: str) -> str:
    """Redis key для множества активных задач данного движка."""
    return f"lmstudio:{engine}:active_jobs"


def _pending_unload_key(engine: str) -> str:
    """Redis key для отложенной выгрузки."""
    return f"lmstudio:{engine}:pending_unload"


def _get_redis_pool() -> redis.ConnectionPool:
    """Redis connection pool (паттерн из queue_checker.py)."""
    global _redis_pool
    if _redis_pool is None:
        with _pool_lock:
            if _redis_pool is None:
                parsed = urlparse(settings.redis_url)
                _redis_pool = redis.ConnectionPool(
                    host=parsed.hostname or "localhost",
                    port=parsed.port or 6379,
                    db=int(parsed.path.lstrip("/") or 0),
                    password=parsed.password,
                    decode_responses=True,
                    max_connections=10,
                )
    return _redis_pool


def _get_redis_client() -> redis.Redis:
    return redis.Redis(connection_pool=_get_redis_pool())


# ── Универсальные функции ───────────────────────────────────────────

def acquire_lmstudio(engine: str, job_id: str) -> int:
    """Зарегистрировать начало задачи для LM Studio движка. Возвращает счётчик."""
    try:
        client = _get_redis_client()
        key = _active_key(engine)
        client.sadd(key, job_id)
        # TTL обновляется при каждом acquire — страховка от крашей
        client.expire(key, _SAFETY_TTL)
        # Отменяем pending unload — новая задача пришла
        client.delete(_pending_unload_key(engine))
        count = client.scard(key)
        logger.info(
            f"{engine} acquire: job={job_id}, active_tasks={count}",
            extra={"event": f"{engine}_acquire", "job_id": job_id},
        )
        return count
    except Exception as e:
        logger.warning(f"{engine} acquire failed (fallback to 1): {e}")
        return 1


def release_lmstudio(engine: str, job_id: str) -> int:
    """Снять регистрацию задачи для LM Studio движка. Возвращает оставшийся счётчик."""
    try:
        client = _get_redis_client()
        key = _active_key(engine)
        client.srem(key, job_id)
        count = client.scard(key)
        if count > 0:
            # Обновляем TTL пока есть активные задачи
            client.expire(key, _SAFETY_TTL)
        logger.info(
            f"{engine} release: job={job_id}, active_tasks={count}",
            extra={"event": f"{engine}_release", "job_id": job_id},
        )
        return count
    except Exception as e:
        logger.warning(f"{engine} release failed (fallback: will unload): {e}")
        return 0


def schedule_pending_unload(engine: str) -> None:
    """Запланировать отложенную выгрузку модели (если нет активных задач).

    Сохраняет timestamp, когда выгрузка была запланирована.
    Background loop через UNLOAD_GRACE_SECONDS проверит и выгрузит.
    """
    import time

    try:
        client = _get_redis_client()
        count = client.scard(_active_key(engine))
        if count == 0:
            client.set(
                _pending_unload_key(engine),
                str(time.time()),
                ex=UNLOAD_GRACE_SECONDS + 60,  # +60s запас чтобы loop успел проверить
            )
            logger.info(
                f"{engine}: pending unload запланирован (grace={UNLOAD_GRACE_SECONDS}s)",
                extra={"event": f"{engine}_pending_unload"},
            )
    except Exception as e:
        logger.warning(f"{engine} schedule_pending_unload failed: {e}")


def check_and_unload_models() -> None:
    """Проверить pending unloads и выгрузить модели если grace period истёк.

    Вызывается из background loop (каждые 30 сек).
    """
    import time

    for engine in ("chandra",):
        try:
            client = _get_redis_client()
            pending_ts = client.get(_pending_unload_key(engine))
            if pending_ts is None:
                continue

            elapsed = time.time() - float(pending_ts)
            if elapsed < UNLOAD_GRACE_SECONDS:
                continue  # Grace period ещё не истёк

            # Проверяем что нет новых активных задач
            count = client.scard(_active_key(engine))
            if count > 0:
                # Новая задача пришла, удаляем pending
                client.delete(_pending_unload_key(engine))
                continue

            # Grace period истёк, нет активных — выгружаем
            client.delete(_pending_unload_key(engine))
            _do_unload_model(engine)

        except Exception as e:
            logger.warning(f"check_and_unload_models({engine}): {e}")


def _do_unload_model(engine: str) -> None:
    """Выполнить выгрузку модели LM Studio."""
    from .settings import settings

    base_url = None
    if engine == "chandra":
        base_url = getattr(settings, "chandra_base_url", None)

    if not base_url:
        return

    try:
        import requests

        resp = requests.get(f"{base_url}/api/v1/models", timeout=10)
        if resp.status_code != 200:
            return

        # Определяем точный model key для matching
        if engine == "chandra":
            from rd_core.ocr._chandra_common import CHANDRA_MODEL_KEY
            model_key_lower = CHANDRA_MODEL_KEY.lower()
        else:
            model_key_lower = engine

        for m in resp.json().get("models", []):
            if model_key_lower in m.get("key", "").lower():
                for inst in m.get("loaded_instances", []):
                    requests.post(
                        f"{base_url}/api/v1/models/unload",
                        json={"instance_id": inst["id"]},
                        timeout=30,
                    )
                    logger.info(
                        f"{engine}: модель выгружена после grace period: {inst['id']}",
                        extra={"event": f"{engine}_delayed_unload"},
                    )
                break
    except Exception as e:
        logger.warning(f"_do_unload_model({engine}): {e}")


# ── Обратная совместимость (Chandra) ────────────────────────────────

def acquire_chandra(job_id: str) -> int:
    """Обратная совместимость: acquire для Chandra."""
    return acquire_lmstudio("chandra", job_id)


def release_chandra(job_id: str) -> int:
    """Обратная совместимость: release для Chandra."""
    return release_lmstudio("chandra", job_id)


# ══════════════════════════════════════════════════════════════════════
# Chandra Speed Guard: cross-worker мониторинг скорости и авто-reload.
#
# ChandraBackend.recognize() после каждого POST:
#   - elapsed >= chandra_slow_request_seconds или timeout → record_slow_sample()
#   - быстрый успех → reset_slow_counter()
# При counter >= chandra_slow_consecutive_requests ИЛИ has_foreign_loaded_model →
# try_speed_guard_reload() выполняет полный unload всех моделей LM Studio +
# reload chandra-ocr-2 (под Redis-локом, с drain in-flight, с cooldown).
# ══════════════════════════════════════════════════════════════════════

from rd_core.ocr._chandra_common import (
    CHANDRA_LOAD_CONFIG,
    CHANDRA_MODEL_KEY,
    SPEEDGUARD_INFLIGHT_KEY,
    SPEEDGUARD_LAST_RELOAD_KEY,
    SPEEDGUARD_LOCK_KEY,
    SPEEDGUARD_PAUSE_FLAG_KEY,
    SPEEDGUARD_SLOW_COUNTER_KEY,
    get_ngrok_auth,
)

# ── Slow-counter (cross-worker) ─────────────────────────────────────

def record_slow_sample() -> int:
    """Зарегистрировать медленный запрос. Возвращает текущее значение счётчика."""
    try:
        client = _get_redis_client()
        count = client.incr(SPEEDGUARD_SLOW_COUNTER_KEY)
        client.expire(SPEEDGUARD_SLOW_COUNTER_KEY, 3600)
        return int(count)
    except Exception as e:
        logger.warning(f"speed_guard record_slow_sample failed: {e}")
        return 0


def reset_slow_counter() -> None:
    """Сбросить счётчик медленных запросов (быстрый успех / после reload)."""
    try:
        _get_redis_client().delete(SPEEDGUARD_SLOW_COUNTER_KEY)
    except Exception as e:
        logger.warning(f"speed_guard reset_slow_counter failed: {e}")


def get_slow_counter() -> int:
    """Текущее значение счётчика медленных запросов."""
    try:
        val = _get_redis_client().get(SPEEDGUARD_SLOW_COUNTER_KEY)
        return int(val) if val else 0
    except Exception as e:
        logger.warning(f"speed_guard get_slow_counter failed: {e}")
        return 0


# ── In-flight counter (для drain перед reload) ──────────────────────

def incr_inflight() -> int:
    """Зарегистрировать начало POST'а к Chandra."""
    try:
        client = _get_redis_client()
        count = client.incr(SPEEDGUARD_INFLIGHT_KEY)
        client.expire(SPEEDGUARD_INFLIGHT_KEY, 600)
        return int(count)
    except Exception as e:
        logger.warning(f"speed_guard incr_inflight failed: {e}")
        return 0


def decr_inflight() -> int:
    """Зарегистрировать завершение POST'а (любым путём: успех/ошибка/таймаут)."""
    try:
        client = _get_redis_client()
        count = int(client.decr(SPEEDGUARD_INFLIGHT_KEY))
        if count < 0:
            client.set(SPEEDGUARD_INFLIGHT_KEY, "0", ex=600)
            return 0
        return count
    except Exception as e:
        logger.warning(f"speed_guard decr_inflight failed: {e}")
        return 0


def get_inflight() -> int:
    """Текущее число in-flight POST'ов."""
    try:
        val = _get_redis_client().get(SPEEDGUARD_INFLIGHT_KEY)
        return int(val) if val else 0
    except Exception as e:
        logger.warning(f"speed_guard get_inflight failed: {e}")
        return 0


# ── Pause flag (блокирует новые POST на время reload) ───────────────

def set_reload_in_progress(ttl_seconds: int) -> None:
    """Установить флаг 'reload в процессе'. ChandraBackend паузит новые POST."""
    try:
        _get_redis_client().set(SPEEDGUARD_PAUSE_FLAG_KEY, "1", ex=max(ttl_seconds, 1))
    except Exception as e:
        logger.warning(f"speed_guard set_reload_in_progress failed: {e}")


def is_reload_in_progress() -> bool:
    """Проверить, идёт ли сейчас reload."""
    try:
        return bool(_get_redis_client().exists(SPEEDGUARD_PAUSE_FLAG_KEY))
    except Exception as e:
        logger.warning(f"speed_guard is_reload_in_progress failed: {e}")
        return False


def clear_reload_in_progress() -> None:
    """Снять флаг reload — воркеры могут возобновить POST'ы."""
    try:
        _get_redis_client().delete(SPEEDGUARD_PAUSE_FLAG_KEY)
    except Exception as e:
        logger.warning(f"speed_guard clear_reload_in_progress failed: {e}")


# ── Reload lock и cooldown ──────────────────────────────────────────

def acquire_reload_lock(ttl_seconds: int) -> bool:
    """Эксклюзивный лок на reload (Redis SET NX EX). True если лок взят."""
    try:
        result = _get_redis_client().set(
            SPEEDGUARD_LOCK_KEY, str(time.time()), nx=True, ex=max(ttl_seconds, 1)
        )
        return bool(result)
    except Exception as e:
        logger.warning(f"speed_guard acquire_reload_lock failed: {e}")
        return False


def release_reload_lock() -> None:
    """Освободить лок reload."""
    try:
        _get_redis_client().delete(SPEEDGUARD_LOCK_KEY)
    except Exception as e:
        logger.warning(f"speed_guard release_reload_lock failed: {e}")


def is_in_cooldown(cooldown_seconds: int) -> bool:
    """True если последний reload был меньше cooldown_seconds назад."""
    try:
        val = _get_redis_client().get(SPEEDGUARD_LAST_RELOAD_KEY)
        if not val:
            return False
        return (time.time() - float(val)) < cooldown_seconds
    except Exception as e:
        logger.warning(f"speed_guard is_in_cooldown failed: {e}")
        return False


def mark_reload_completed() -> None:
    """Записать timestamp успешного reload (запускает cooldown)."""
    try:
        _get_redis_client().set(SPEEDGUARD_LAST_RELOAD_KEY, str(time.time()), ex=3600)
    except Exception as e:
        logger.warning(f"speed_guard mark_reload_completed failed: {e}")


# ── Детект загруженных моделей в LM Studio ──────────────────────────

def list_loaded_lmstudio_models(base_url: str) -> list[dict]:
    """Список загруженных моделей LM Studio.

    Возвращает [{"key": <model_key>, "instances": [<instance_id>, ...]}] для моделей
    с непустым loaded_instances. При сетевой ошибке — пустой список (не делаем выводов).
    """
    if not base_url:
        return []
    try:
        import requests

        resp = requests.get(
            f"{base_url}/api/v1/models", timeout=10, auth=get_ngrok_auth()
        )
        if resp.status_code != 200:
            return []
        result = []
        for m in resp.json().get("models", []) or []:
            instances = m.get("loaded_instances") or []
            if not instances:
                continue
            inst_ids = [inst.get("id") for inst in instances if inst.get("id")]
            if inst_ids:
                result.append({"key": m.get("key", ""), "instances": inst_ids})
        return result
    except Exception as e:
        logger.warning(f"speed_guard list_loaded_lmstudio_models failed: {e}")
        return []


def has_foreign_loaded_model(loaded: list[dict]) -> bool:
    """True если в списке загруженных моделей есть НЕ chandra-ocr-2."""
    chandra_key = CHANDRA_MODEL_KEY.lower()
    for entry in loaded:
        key = (entry.get("key") or "").lower()
        if key and key != chandra_key:
            return True
    return False


# ── Drain in-flight ─────────────────────────────────────────────────

def wait_for_inflight_drain(timeout_seconds: int) -> bool:
    """Дождаться завершения всех in-flight POST'ов И активных задач.

    Возвращает True, если оба счётчика обнулились в пределах timeout.
    """
    deadline = time.monotonic() + max(timeout_seconds, 1)
    try:
        client = _get_redis_client()
        while time.monotonic() < deadline:
            inflight = get_inflight()
            active = 0
            try:
                active = int(client.scard(_active_key("chandra")) or 0)
            except Exception:
                pass
            if inflight <= 0 and active <= 0:
                return True
            time.sleep(0.5)
        return False
    except Exception as e:
        logger.warning(f"speed_guard wait_for_inflight_drain failed: {e}")
        return False


# ── Полный reload LM Studio ─────────────────────────────────────────

def _post_unload_instance(base_url: str, instance_id: str, model_key: str) -> bool:
    """POST /api/v1/models/unload одного instance. True при успехе."""
    import requests

    try:
        resp = requests.post(
            f"{base_url}/api/v1/models/unload",
            json={"instance_id": instance_id},
            timeout=30,
            auth=get_ngrok_auth(),
        )
        if resp.status_code == 200:
            logger.info(
                f"speed_guard: выгружен {model_key}/{instance_id}",
                extra={
                    "event": "speed_guard_unload",
                    "model_key": model_key,
                    "instance_id": instance_id,
                },
            )
            return True
        logger.warning(
            f"speed_guard unload {model_key}/{instance_id} HTTP {resp.status_code}: "
            f"{resp.text[:200]}"
        )
        return False
    except Exception as e:
        logger.warning(f"speed_guard unload {model_key}/{instance_id} exception: {e}")
        return False


def _post_load_chandra(base_url: str) -> bool:
    """POST /api/v1/models/load для chandra-ocr-2 с CHANDRA_LOAD_CONFIG.

    При HTTP 400 unrecognized_keys — retry без отвергнутых ключей (паттерн chandra.py).
    """
    import requests

    load_config = {**CHANDRA_LOAD_CONFIG}
    auth = get_ngrok_auth()

    def _do_load(cfg: dict):
        payload = {"model": CHANDRA_MODEL_KEY, "echo_load_config": True, **cfg}
        return requests.post(
            f"{base_url}/api/v1/models/load", json=payload, timeout=120, auth=auth
        )

    try:
        resp = _do_load(load_config)
        if resp.status_code == 400:
            try:
                err = resp.json().get("error", {})
                if err.get("code") == "unrecognized_keys":
                    msg = err.get("message", "")
                    bad_keys = [
                        k.strip().strip("'\"")
                        for k in msg.split(":")[-1].split(",")
                    ]
                    for k in bad_keys:
                        load_config.pop(k, None)
                    logger.warning(
                        f"speed_guard: load retry без ключей {bad_keys}"
                    )
                    resp = _do_load(load_config)
            except Exception:
                pass
        if resp.status_code == 200:
            try:
                data = resp.json()
                lc = data.get("load_config", {})
                logger.info(
                    f"speed_guard: chandra-ocr-2 загружена, "
                    f"context_length={lc.get('context_length', '?')}, "
                    f"время={data.get('load_time_seconds', '?')}с"
                )
            except Exception:
                pass
            return True
        logger.error(
            f"speed_guard load chandra-ocr-2 HTTP {resp.status_code}: {resp.text[:300]}"
        )
        return False
    except Exception as e:
        logger.error(f"speed_guard load chandra-ocr-2 exception: {e}")
        return False


def perform_full_lmstudio_reload(base_url: str, reason: str) -> bool:
    """Выгрузить ВСЕ загруженные модели LM Studio и загрузить chandra-ocr-2 заново.

    Reload выполняется безусловно: даже если загружена только chandra-ocr-2,
    цикл unload+load всё равно проходит (пользовательское требование).

    Returns:
        True при успешной загрузке chandra-ocr-2. Cooldown ставится только при успехе.
    """
    start = time.monotonic()
    loaded = list_loaded_lmstudio_models(base_url)

    unloaded_count = 0
    for entry in loaded:
        model_key = entry.get("key", "")
        for inst_id in entry.get("instances", []):
            if _post_unload_instance(base_url, inst_id, model_key):
                unloaded_count += 1

    ok = _post_load_chandra(base_url)
    duration_ms = int((time.monotonic() - start) * 1000)

    if ok:
        mark_reload_completed()
        reset_slow_counter()
        logger.info(
            f"speed_guard: reload завершён (reason={reason}, "
            f"unloaded={unloaded_count}, duration={duration_ms}ms)",
            extra={
                "event": "speed_guard_reload_completed",
                "reason": reason,
                "unloaded_count": unloaded_count,
                "duration_ms": duration_ms,
            },
        )
    else:
        logger.error(
            f"speed_guard: reload НЕ удался (reason={reason}, "
            f"unloaded={unloaded_count}, duration={duration_ms}ms)",
            extra={
                "event": "speed_guard_reload_failed",
                "reason": reason,
                "unloaded_count": unloaded_count,
                "duration_ms": duration_ms,
            },
        )
    return ok


# ── Orchestrator (точка входа из ChandraBackend) ────────────────────

def try_speed_guard_reload(base_url: str, reason: str) -> bool:
    """Попытаться выполнить speed-guard reload.

    Игнорирует вызов если:
      - speed_guard выключен в settings;
      - активен cooldown после предыдущего reload;
      - reload-lock уже занят другим воркером.

    Иначе: ставит pause-flag, ждёт drain in-flight, выполняет полный reload,
    снимает flag и lock в finally.
    """
    if not base_url:
        return False
    if not getattr(settings, "chandra_speed_guard_enabled", False):
        return False
    if is_in_cooldown(int(settings.chandra_slow_reload_cooldown_seconds)):
        return False

    lock_ttl = int(settings.chandra_speed_guard_lock_ttl)
    if not acquire_reload_lock(lock_ttl):
        # Другой воркер уже делает reload.
        return False

    drain_timeout = int(settings.chandra_speed_guard_drain_timeout)
    set_reload_in_progress(drain_timeout + lock_ttl)
    logger.warning(
        f"speed_guard: reload triggered (reason={reason})",
        extra={"event": "speed_guard_reload_triggered", "reason": reason},
    )
    try:
        drained = wait_for_inflight_drain(drain_timeout)
        if not drained:
            logger.warning(
                f"speed_guard: drain timeout ({drain_timeout}s), "
                f"продолжаем reload (inflight={get_inflight()})",
                extra={
                    "event": "speed_guard_drain_timeout",
                    "drain_timeout": drain_timeout,
                    "inflight": get_inflight(),
                },
            )
        return perform_full_lmstudio_reload(base_url, reason)
    finally:
        clear_reload_in_progress()
        release_reload_lock()
