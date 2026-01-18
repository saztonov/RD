"""HTTP utilities for OCR backends."""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def create_session_with_retries(
    retries: int = 3,
    backoff_factor: float = 1.0,
    status_forcelist: tuple = (429, 502, 503, 504),
    pool_connections: int = 5,
    pool_maxsize: int = 10,
) -> requests.Session:
    """Create HTTP session with retry strategy.

    Args:
        retries: Number of retry attempts
        backoff_factor: Backoff factor between retries (delay = backoff_factor * 2^retry)
        status_forcelist: HTTP status codes to retry (includes 429 for rate limiting)
        pool_connections: Number of connection pools
        pool_maxsize: Max connections per pool

    Returns:
        Configured requests.Session
    """
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        respect_retry_after_header=True,
        allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
    )
    adapter = HTTPAdapter(
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        max_retries=retry,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
