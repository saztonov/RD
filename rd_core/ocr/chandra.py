"""Chandra OCR Backend (LM Studio / OpenAI-compatible API) — sync"""
import logging
import threading
import time
from typing import Optional

import requests
from PIL import Image

from rd_core.ocr._backend_timing import BackendTimingMixin
from rd_core.ocr._chandra_common import (
    CHANDRA_LOAD_CONFIG,
    CHANDRA_MAX_IMAGE_SIZE,
    CHANDRA_MODEL_KEY,
    TRANSIENT_CODES,
    build_payload,
    check_non_retriable_error,
    get_ngrok_auth,
    init_base_url,
    needs_model_reload,
    parse_response,
)
from rd_core.ocr.http_utils import create_retry_session, ocr_proxies
from rd_core.ocr.utils import image_to_base64
from rd_core.ocr_result import is_error, make_error

logger = logging.getLogger(__name__)


# ── Speed Guard hooks (lazy lookup в server-слой) ───────────────────
# rd_core не должен жёстко зависеть от services.remote_ocr.server. При наличии
# server-модуля используем функции speed-guard (cross-worker Redis-coordination),
# иначе все хуки — no-op (например, при автономном использовании ChandraBackend
# из desktop client).

class _NoopGuardHooks:
    """Заглушки speed-guard функций для случаев без server-слоя."""

    settings = None

    @staticmethod
    def record_slow():
        return 0

    @staticmethod
    def reset_slow():
        return None

    @staticmethod
    def incr_inflight():
        return 0

    @staticmethod
    def decr_inflight():
        return 0

    @staticmethod
    def is_paused():
        return False

    @staticmethod
    def list_loaded(_base_url):
        return []

    @staticmethod
    def has_foreign(_loaded):
        return False

    @staticmethod
    def try_reload(_base_url, _reason):
        return False


_GUARD_HOOKS: Optional[object] = None


def _get_guard_hooks():
    """Lazy-импорт speed-guard функций из server-слоя.

    При отсутствии server-модуля или ошибке импорта — все хуки no-op.
    Результат кэшируется в module-level переменной.
    """
    global _GUARD_HOOKS
    if _GUARD_HOOKS is not None:
        return _GUARD_HOOKS
    try:
        from services.remote_ocr.server.lmstudio_lifecycle import (
            decr_inflight,
            has_foreign_loaded_model,
            incr_inflight,
            is_reload_in_progress,
            list_loaded_lmstudio_models,
            record_slow_sample,
            reset_slow_counter,
            try_speed_guard_reload,
        )
        from services.remote_ocr.server.settings import settings as _server_settings

        class _RealGuardHooks:
            settings = _server_settings
            record_slow = staticmethod(record_slow_sample)
            reset_slow = staticmethod(reset_slow_counter)
            incr_inflight = staticmethod(incr_inflight)
            decr_inflight = staticmethod(decr_inflight)
            is_paused = staticmethod(is_reload_in_progress)
            list_loaded = staticmethod(list_loaded_lmstudio_models)
            has_foreign = staticmethod(has_foreign_loaded_model)
            try_reload = staticmethod(try_speed_guard_reload)

        _GUARD_HOOKS = _RealGuardHooks()
    except Exception as exc:  # pragma: no cover (fallback ветка)
        logger.debug(f"Speed-guard hooks недоступны: {exc}")
        _GUARD_HOOKS = _NoopGuardHooks()
    return _GUARD_HOOKS


class ChandraBackend(BackendTimingMixin):
    """OCR через Chandra модель (LM Studio, OpenAI-compatible API)"""

    # Один контролируемый retry с короткой паузой.
    # Длинные backoff (30/60/120) убраны: сетевая ошибка → быстрый отказ →
    # ранний fallback в pass2_strips на text_fallback backend.
    _MAX_APP_RETRIES = 1
    _APP_RETRY_DELAYS = [5]

    def __init__(self, base_url: Optional[str] = None, http_timeout: int = 90, **kwargs):
        self.base_url = init_base_url(base_url)
        self._model_id: Optional[str] = None
        self._model_lock = threading.Lock()
        self._auth = get_ngrok_auth()
        ngrok_proxies = ocr_proxies(ngrok_mode=True)
        self.session = create_retry_session(auth=self._auth, ngrok_mode=True, proxies=ngrok_proxies)
        self._preload_session = create_retry_session(
            auth=self._auth, preload_mode=True, proxies=ngrok_proxies
        )
        self._deadline: Optional[float] = None
        self._cancel_event: Optional[threading.Event] = None
        self._http_timeout = http_timeout
        logger.info(f"ChandraBackend инициализирован (base_url: {self.base_url})")

    def _discover_model(self) -> str:
        if self._model_id:
            return self._model_id

        with self._model_lock:
            if self._model_id:
                return self._model_id

            self._ensure_model_loaded()

            try:
                resp = self.session.get(f"{self.base_url}/v1/models", timeout=30)
                if resp.status_code == 200:
                    model_key_lower = CHANDRA_MODEL_KEY.lower()
                    for m in resp.json().get("data", []):
                        mid = m.get("id", "").lower()
                        if mid == model_key_lower:
                            self._model_id = m["id"]
                            logger.info(
                                f"Chandra модель найдена: requested={CHANDRA_MODEL_KEY}, "
                                f"used={self._model_id}"
                            )
                            return self._model_id
            except Exception as e:
                logger.warning(f"Ошибка определения модели Chandra: {e}")

            self._model_id = CHANDRA_MODEL_KEY
            logger.info(
                f"Chandra модель не найдена в /v1/models, используется fallback: "
                f"{self._model_id}"
            )
            return self._model_id

    def preload(self) -> None:
        """Предзагрузка модели. Non-fatal: при ошибке/таймауте логируем и продолжаем."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

        PRELOAD_TIMEOUT = 60
        start = time.time()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._discover_model)
                future.result(timeout=PRELOAD_TIMEOUT)
            elapsed = time.time() - start
            logger.info(f"Chandra модель предзагружена: {self._model_id} ({elapsed:.1f}с)")
        except FuturesTimeoutError:
            elapsed = time.time() - start
            logger.warning(f"Chandra preload timeout ({elapsed:.1f}с), продолжаем без preload")
        except Exception as e:
            elapsed = time.time() - start
            logger.warning(f"Chandra preload не удался ({elapsed:.1f}с, non-fatal): {e}")

    def _try_discover_and_load(self, failed_resp, load_config: dict) -> bool:
        """При model_not_found — найти модель через /v1/models и загрузить."""
        try:
            err = failed_resp.json().get("error", {})
            if err.get("type") != "model_not_found":
                return False
        except Exception:
            return False

        logger.info("Preload: model_not_found, пробуем auto-discovery через /v1/models...")
        try:
            resp = self._preload_session.get(f"{self.base_url}/v1/models", timeout=10)
            if resp.status_code != 200:
                return False

            model_key_lower = CHANDRA_MODEL_KEY.lower()
            for m in resp.json().get("data", []):
                mid = m.get("id", "").lower()
                if mid == model_key_lower:
                    discovered_id = m["id"]
                    logger.info(f"Preload: найдена модель через discovery: {discovered_id}")
                    retry_config = {**load_config}
                    retry_resp = self._load_model_with_retry(discovered_id, retry_config)
                    if retry_resp and retry_resp.status_code == 200:
                        load_data = retry_resp.json()
                        lc = load_data.get("load_config", {})
                        logger.info(
                            f"Preload: модель загружена через discovery: "
                            f"context_length={lc.get('context_length', '?')}, "
                            f"время={load_data.get('load_time_seconds', '?')}с"
                        )
                        return True
                    else:
                        logger.warning(f"Preload: повторная загрузка {discovered_id} не удалась")
                        return False

            logger.warning("Preload: модель не найдена через /v1/models discovery")
        except Exception as e:
            logger.warning(f"Preload: auto-discovery ошибка: {e}")
        return False

    def _load_model_with_retry(self, model_key: str, load_config: dict):
        """POST /api/v1/models/load с retry при unrecognized_keys."""
        payload = {"model": model_key, "echo_load_config": True, **load_config}
        logger.info(f"Preload: POST /api/v1/models/load {model_key} (context_length={load_config.get('context_length')})...")
        resp = self._preload_session.post(
            f"{self.base_url}/api/v1/models/load", json=payload, timeout=120,
        )
        if resp.status_code == 400:
            try:
                err = resp.json().get("error", {})
                if err.get("code") == "unrecognized_keys":
                    msg = err.get("message", "")
                    bad_keys = [k.strip().strip("'\"") for k in msg.split(":")[-1].split(",")]
                    for k in bad_keys:
                        load_config.pop(k, None)
                    logger.warning(f"Preload: LM Studio не поддерживает ключи {bad_keys}, retry без них")
                    payload = {"model": model_key, "echo_load_config": True, **load_config}
                    resp = self._preload_session.post(
                        f"{self.base_url}/api/v1/models/load", json=payload, timeout=120,
                    )
            except Exception:
                pass
        return resp

    def _ensure_model_loaded(self) -> None:
        required_ctx = CHANDRA_LOAD_CONFIG["context_length"]
        try:
            logger.info(f"Preload: GET /api/v1/models (timeout=10s)...")
            resp = self._preload_session.get(f"{self.base_url}/api/v1/models", timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Preload: GET /api/v1/models → {resp.status_code}, пропускаем")
                return

            models = resp.json().get("models", [])
            actual_key = CHANDRA_MODEL_KEY

            model_key_lower = CHANDRA_MODEL_KEY.lower()
            for m in models:
                if m.get("key", "").lower() == model_key_lower:
                    loaded = m.get("loaded_instances", [])
                    need_reload, reason = needs_model_reload(loaded, required_ctx)

                    if not need_reload:
                        ctx_list = [inst.get("context_length", "?") for inst in loaded]
                        logger.info(
                            f"Preload: модель {m['key']} уже загружена ({reason}), "
                            f"instances={len(loaded)}, context_lengths={ctx_list}"
                        )
                        return

                    logger.info(f"Preload: модель {m['key']}: {reason}, выполняем reload")
                    for inst in loaded:
                        try:
                            self._preload_session.post(
                                f"{self.base_url}/api/v1/models/unload",
                                json={"instance_id": inst["id"]}, timeout=30,
                            )
                            logger.debug(f"Выгружен инстанс: {inst['id']}")
                        except Exception as e:
                            logger.warning(f"Ошибка выгрузки {inst.get('id')}: {e}")
                    actual_key = m.get("key", CHANDRA_MODEL_KEY)
                    break

            load_config = {**CHANDRA_LOAD_CONFIG}
            load_resp = self._load_model_with_retry(actual_key, load_config)

            if load_resp and load_resp.status_code == 200:
                load_data = load_resp.json()
                lc = load_data.get("load_config", {})
                logger.info(
                    f"Preload: модель загружена: context_length={lc.get('context_length', '?')}, "
                    f"время={load_data.get('load_time_seconds', '?')}с"
                )
            elif load_resp:
                # Auto-discovery: при model_not_found ищем модель по /v1/models
                discovered = self._try_discover_and_load(load_resp, load_config)
                if not discovered:
                    logger.warning(f"Preload: ошибка загрузки: {load_resp.status_code} - {load_resp.text[:300]}")

        except Exception as e:
            logger.warning(f"Preload: native API недоступен: {e}")

    def unload_model(self) -> None:
        if not self._model_id:
            return
        try:
            resp = self.session.get(f"{self.base_url}/api/v1/models", timeout=10)
            if resp.status_code != 200:
                return

            model_key_lower = CHANDRA_MODEL_KEY.lower()
            for m in resp.json().get("models", []):
                if m.get("key", "").lower() == model_key_lower:
                    for inst in m.get("loaded_instances", []):
                        self.session.post(
                            f"{self.base_url}/api/v1/models/unload",
                            json={"instance_id": inst["id"]}, timeout=30,
                        )
                        logger.info(f"Модель выгружена: {inst['id']}")
                    break
        except Exception as e:
            logger.warning(f"Ошибка выгрузки модели: {e}")

    def supports_pdf_input(self) -> bool:
        return False

    def force_reload_all_models(self, reason: str) -> bool:
        """Запросить полную перезагрузку LM Studio через speed-guard orchestrator.

        Выгружает ВСЕ загруженные модели LM Studio и грузит заново chandra-ocr-2
        (под Redis-локом, с cooldown). При успехе сбрасывает локальный _model_id —
        следующий recognize выполнит повторный discover.
        """
        hooks = _get_guard_hooks()
        ok = bool(hooks.try_reload(self.base_url, reason))
        if ok:
            self._model_id = None
        return ok

    def _handle_slow_sample(
        self,
        *,
        elapsed: float,
        is_timeout: bool,
        completion_tokens: int,
        text_len: int,
    ) -> None:
        """Зарегистрировать медленный запрос и при достижении порога — триггер reload."""
        hooks = _get_guard_hooks()
        guard_settings = hooks.settings

        if guard_settings is not None and not getattr(
            guard_settings, "chandra_speed_guard_enabled", False
        ):
            return

        count = int(hooks.record_slow() or 0)
        threshold = int(
            getattr(guard_settings, "chandra_slow_consecutive_requests", 3) or 3
        )

        tps = (completion_tokens / elapsed) if (elapsed > 0 and completion_tokens > 0) else 0.0
        cps = (text_len / elapsed) if (elapsed > 0 and text_len > 0) else 0.0
        logger.warning(
            f"Chandra slow sample: elapsed={elapsed:.1f}s, "
            f"is_timeout={is_timeout}, slow_counter={count}/{threshold}",
            extra={
                "event": "chandra_request_metrics",
                "elapsed_sec": round(elapsed, 2),
                "is_slow": True,
                "is_timeout": is_timeout,
                "completion_tokens": completion_tokens,
                "tokens_per_sec": round(tps, 2),
                "chars_per_sec": round(cps, 2),
                "slow_counter": count,
            },
        )

        # Триггер 1: счётчик достиг порога.
        if count >= threshold:
            reason = "timeout_streak" if is_timeout else "slow_streak"
            self.force_reload_all_models(reason)
            return

        # Триггер 2: загружена чужая модель (мгновенно, без ожидания окна).
        try:
            loaded = hooks.list_loaded(self.base_url)
            if hooks.has_foreign(loaded):
                self.force_reload_all_models("foreign_loaded")
        except Exception as exc:
            logger.debug(f"speed_guard foreign-check failed: {exc}")

    def _handle_fast_success(
        self,
        *,
        elapsed: float,
        completion_tokens: int,
        text_len: int,
    ) -> None:
        """Зарегистрировать быстрый успешный запрос и сбросить slow-counter."""
        hooks = _get_guard_hooks()
        guard_settings = hooks.settings

        tps = (completion_tokens / elapsed) if (elapsed > 0 and completion_tokens > 0) else 0.0
        cps = (text_len / elapsed) if (elapsed > 0 and text_len > 0) else 0.0
        logger.info(
            f"Chandra metrics: elapsed={elapsed:.1f}s, "
            f"completion_tokens={completion_tokens}, tps={tps:.1f}",
            extra={
                "event": "chandra_request_metrics",
                "elapsed_sec": round(elapsed, 2),
                "is_slow": False,
                "is_timeout": False,
                "completion_tokens": completion_tokens,
                "tokens_per_sec": round(tps, 2),
                "chars_per_sec": round(cps, 2),
            },
        )

        if guard_settings is not None and not getattr(
            guard_settings, "chandra_speed_guard_enabled", False
        ):
            return

        hooks.reset_slow()

    def recognize(
        self,
        image: Optional[Image.Image],
        prompt: Optional[dict] = None,
        json_mode: bool = None,
        pdf_file_path: Optional[str] = None,
    ) -> str:
        if image is None:
            return make_error("Chandra требует изображение")

        try:
            model_id = self._discover_model()
            img_b64 = image_to_base64(image, max_size=CHANDRA_MAX_IMAGE_SIZE)
            payload = build_payload(model_id, prompt, img_b64)

            hooks = _get_guard_hooks()
            guard_settings = hooks.settings
            slow_threshold = float(
                getattr(guard_settings, "chandra_slow_request_seconds", 90) or 90
            )

            last_error = None
            response_json = None
            for attempt in range(self._MAX_APP_RETRIES + 1):
                if attempt > 0:
                    delay = self._APP_RETRY_DELAYS[min(attempt - 1, len(self._APP_RETRY_DELAYS) - 1)]

                    # Проверяем time budget перед ожиданием
                    if self._is_budget_exhausted(delay):
                        logger.warning(
                            f"Chandra: time budget exhausted before retry {attempt}, "
                            f"aborting (last error: {last_error})"
                        )
                        return make_error(
                            f"Chandra: time budget exhausted после {attempt - 1} попыток"
                        )

                    logger.warning(
                        f"Chandra API retry {attempt}/{self._MAX_APP_RETRIES}, "
                        f"ожидание {delay}с (предыдущая ошибка: {last_error})"
                    )
                    if self._interruptible_sleep(delay):
                        return make_error("Chandra: операция отменена")

                # Проверяем бюджет перед HTTP-запросом (timeout может быть долгим)
                if self._is_budget_exhausted(self._http_timeout):
                    logger.warning(
                        f"Chandra: time budget exhausted before request (attempt {attempt}), aborting"
                    )
                    return make_error(
                        f"Chandra: time budget exhausted перед запросом (attempt {attempt})"
                    )

                # Pause-цикл: если идёт speed-guard reload, ждём его завершения.
                # Защитный таймаут (drain + load + запас) предотвращает вечную блокировку.
                pause_deadline = time.monotonic() + (self._http_timeout + 5)
                while hooks.is_paused() and time.monotonic() < pause_deadline:
                    if self._interruptible_sleep(0.5):
                        return make_error("Chandra: операция отменена")

                # ─── Один запрос с замером времени и in-flight трекингом ───
                response = None
                t0 = time.monotonic()
                elapsed = 0.0
                hooks.incr_inflight()
                try:
                    try:
                        response = self.session.post(
                            f"{self.base_url}/v1/chat/completions",
                            headers={
                                "Content-Type": "application/json",
                                "ngrok-skip-browser-warning": "true",
                            },
                            json=payload,
                            timeout=self._http_timeout,
                        )
                        elapsed = time.monotonic() - t0
                    except requests.exceptions.ConnectionError as e:
                        elapsed = time.monotonic() - t0
                        last_error = f"ConnectionError: {e}"
                        logger.warning(
                            f"Chandra connection error (attempt {attempt}): {e}"
                        )
                        # Read timeout приходит как ConnectionError(ReadTimeoutError)
                        # — считаем как slow-sample.
                        self._handle_slow_sample(
                            elapsed=elapsed,
                            is_timeout=True,
                            completion_tokens=0,
                            text_len=0,
                        )
                        if attempt < self._MAX_APP_RETRIES:
                            continue
                        return make_error(
                            f"Chandra: {last_error} после {self._MAX_APP_RETRIES} попыток"
                        )
                    except requests.exceptions.Timeout:
                        elapsed = time.monotonic() - t0
                        last_error = "Timeout"
                        logger.warning(f"Chandra timeout (attempt {attempt})")
                        self._handle_slow_sample(
                            elapsed=elapsed,
                            is_timeout=True,
                            completion_tokens=0,
                            text_len=0,
                        )
                        if attempt < self._MAX_APP_RETRIES:
                            continue
                        return make_error("превышен таймаут запроса к Chandra")
                finally:
                    hooks.decr_inflight()

                if response is None:
                    # Не должно случаться — все ветви выше делают continue/return.
                    continue

                if response.status_code == 200:
                    response_json = response.json()
                    break

                non_retriable = check_non_retriable_error(
                    response.status_code, response.text
                )
                if non_retriable:
                    return non_retriable

                # "Model unloaded" (HTTP 400) — lifecycle race condition,
                # модель была выгружена другим воркером во время нашего запроса.
                # Принудительно перезагружаем модель и ретраим.
                if (
                    response.status_code == 400
                    and "model unloaded" in (response.text or "").lower()
                ):
                    last_error = "Model unloaded (lifecycle race)"
                    logger.warning(
                        f"Chandra: model unloaded mid-request (attempt {attempt}), "
                        f"сбрасываем _model_id и ретраим"
                    )
                    self._model_id = None  # принудительная перезагрузка при следующем _discover_model
                    if attempt < self._MAX_APP_RETRIES:
                        try:
                            self._discover_model()  # перезагрузить модель
                        except Exception as reload_exc:
                            logger.warning(
                                f"Chandra reload после unload не удался: {reload_exc}"
                            )
                        continue
                    return make_error(
                        f"Chandra API: model unloaded после {self._MAX_APP_RETRIES} попыток"
                    )

                if response.status_code in TRANSIENT_CODES:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < self._MAX_APP_RETRIES:
                        logger.warning(
                            f"Chandra transient error {response.status_code} "
                            f"(attempt {attempt}), will retry"
                        )
                        continue
                    return make_error(
                        f"Chandra API: {response.status_code} после {self._MAX_APP_RETRIES} попыток"
                    )

                error_detail = response.text[:500] if response.text else "No details"
                logger.error(
                    f"Chandra API error: {response.status_code} - {error_detail}"
                )
                return make_error(f"Chandra API: {response.status_code}")

            text = parse_response(response_json) if response_json is not None else make_error(
                "Chandra: empty response"
            )
            if not is_error(text):
                logger.debug(f"Chandra OCR: распознано {len(text)} символов")

                # Speed-guard: успешный запрос → fast/slow ветка.
                usage = (response_json or {}).get("usage") or {}
                try:
                    completion_tokens = int(usage.get("completion_tokens") or 0)
                except (TypeError, ValueError):
                    completion_tokens = 0
                if elapsed >= slow_threshold:
                    self._handle_slow_sample(
                        elapsed=elapsed,
                        is_timeout=False,
                        completion_tokens=completion_tokens,
                        text_len=len(text),
                    )
                else:
                    self._handle_fast_success(
                        elapsed=elapsed,
                        completion_tokens=completion_tokens,
                        text_len=len(text),
                    )
            return text

        except Exception as e:
            logger.error(f"Ошибка Chandra OCR: {e}", exc_info=True)
            return make_error(f"Chandra OCR: {e}")
