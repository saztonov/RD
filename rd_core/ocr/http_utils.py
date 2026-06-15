"""Общие HTTP-утилиты для OCR бэкендов (sync и async)."""
import os
from typing import Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from rd_core.ocr.ssl_policy import ocr_ssl_verify


def ocr_proxies(ngrok_mode: bool = False) -> Optional[dict]:
    """Прокси для OCR-сессий из env.

    NGROK_PROXY_URL — прокси для запросов к ngrok-туннелю (приоритет при ngrok_mode).
    OCR_PROXY_URL — общий прокси для остальных OCR-запросов / fallback.
    """
    url = None
    if ngrok_mode:
        url = os.getenv("NGROK_PROXY_URL")
    if not url:
        url = os.getenv("OCR_PROXY_URL")
    if not url:
        return None
    return {"http": url, "https": url}


def create_retry_session(
    auth: Optional[Tuple[str, str]] = None,
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple = (502, 503, 504),
    ngrok_mode: bool = False,
    preload_mode: bool = False,
    verify: Optional[Union[bool, str]] = None,
    proxies: Optional[dict] = None,
) -> requests.Session:
    """Создать requests.Session с retry и connection pooling.

    Args:
        ngrok_mode: расширенный retry для нестабильного ngrok tunnel
                    (6 попыток, backoff до ~2 мин, включая 404)
        preload_mode: умеренный retry для preload-операций
                      (2 попытки, backoff ~3с, без 404)
        verify: TLS-проверка. None → политика из env (OCR_VERIFY_SSL / OCR_CA_CERT).
        proxies: dict прокси для requests. None → политика из env
                 (NGROK_PROXY_URL при ngrok_mode, иначе OCR_PROXY_URL).
    """
    if preload_mode:
        total_retries = 2
        backoff_factor = 1.0
        status_forcelist = (502, 503, 504)
    elif ngrok_mode:
        # Намеренно НЕ ретраим POST/timeout на этом уровне.
        # Read-timeouts и connection errors всплывают сразу в backend,
        # который сам решает, делать ли один контролируемый retry или
        # сразу уходить в early failover на text_fallback backend.
        total_retries = 0
        backoff_factor = 0.0
        status_forcelist = ()

    session = requests.Session()
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST"]),
        connect=1 if ngrok_mode else total_retries,
        read=0 if ngrok_mode else total_retries,
    )
    adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # Обход ngrok free tier browser interstitial
    session.headers.update({"ngrok-skip-browser-warning": "true"})
    session.verify = ocr_ssl_verify() if verify is None else verify
    if session.verify is False:
        try:
            from urllib3.exceptions import InsecureRequestWarning
            from urllib3 import disable_warnings
            disable_warnings(InsecureRequestWarning)
        except Exception:
            pass
    resolved_proxies = ocr_proxies(ngrok_mode=ngrok_mode) if proxies is None else proxies
    if resolved_proxies:
        session.proxies.update(resolved_proxies)
    if auth:
        session.auth = auth
    return session
