"""Общие HTTP-утилиты для OCR бэкендов (sync и async)."""
from typing import Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_retry_session(
    auth: Optional[Tuple[str, str]] = None,
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple = (502, 503, 504),
    ngrok_mode: bool = False,
    preload_mode: bool = False,
) -> requests.Session:
    """Создать requests.Session с retry и connection pooling.

    Args:
        ngrok_mode: расширенный retry для нестабильного ngrok tunnel
                    (6 попыток, backoff до ~2 мин, включая 404)
        preload_mode: умеренный retry для preload-операций
                      (2 попытки, backoff ~3с, без 404)
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
    if auth:
        session.auth = auth
    return session
