"""Supabase клиент для хранилища"""
import threading

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from rd_core.supabase_ssl import supabase_ssl_verify

from .logging_config import get_logger
from .settings import settings

# Thread-local storage для Supabase клиентов
_thread_local = threading.local()

logger = get_logger(__name__)


def get_client() -> Client:
    """Получить Supabase клиент (thread-local для thread-safety).

    Supabase идёт через прокси с собственным CA — пробрасываем httpx-клиент
    с нужной TLS-проверкой (OCR_CA_CERT / SUPABASE_CA_CERT) в PostgREST.
    """
    client = getattr(_thread_local, "supabase", None)
    if client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("SUPABASE_URL и SUPABASE_KEY должны быть заданы")
        options = SyncClientOptions(
            httpx_client=httpx.Client(verify=supabase_ssl_verify(), timeout=30.0)
        )
        client = create_client(settings.supabase_url, settings.supabase_key, options)
        _thread_local.supabase = client
    return client


def init_db() -> None:
    """Инициализировать подключение к Supabase (проверка соединения)"""
    try:
        client = get_client()
        client.table("jobs").select("id").limit(1).execute()
        logger.info("Supabase: подключение установлено")
    except Exception as e:
        logger.error(f"Supabase: ошибка подключения: {e}")
        raise
