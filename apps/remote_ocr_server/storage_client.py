"""Supabase клиент для хранилища"""
import threading

from supabase import Client, create_client

from .settings import settings

# Thread-local storage для Supabase клиентов
_thread_local = threading.local()


def get_client() -> Client:
    """Получить Supabase клиент (thread-local для thread-safety)"""
    client = getattr(_thread_local, "supabase", None)
    if client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("SUPABASE_URL и SUPABASE_KEY должны быть заданы")
        client = create_client(settings.supabase_url, settings.supabase_key)
        _thread_local.supabase = client
    return client


def init_db() -> None:
    """Инициализировать подключение к Supabase (проверка соединения)"""
    import logging

    logger = logging.getLogger(__name__)

    try:
        client = get_client()
        client.table("jobs").select("id").limit(1).execute()
        logger.info("✅ Supabase: подключение установлено")
    except Exception as e:
        logger.error(f"❌ Supabase: ошибка подключения: {e}")
        raise
