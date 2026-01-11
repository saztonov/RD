"""Утилита для работы с client_id

Client ID - уникальный идентификатор клиентского приложения,
используется для разделения данных между разными установками.
Хранится в ~/.config/CoreStructure/client_id.txt
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_cached_client_id: str | None = None


def get_config_dir() -> Path:
    """Получить директорию конфигурации приложения"""
    return Path.home() / ".config" / "CoreStructure"


def get_client_id_path() -> Path:
    """Получить путь к файлу client_id"""
    return get_config_dir() / "client_id.txt"


def get_client_id() -> str:
    """Получить или создать client_id

    Returns:
        str: UUID клиента
    """
    global _cached_client_id

    if _cached_client_id is not None:
        return _cached_client_id

    client_id_file = get_client_id_path()

    if client_id_file.exists():
        try:
            client_id = client_id_file.read_text(encoding="utf-8").strip()
            if client_id:
                _cached_client_id = client_id
                logger.debug(f"Client ID loaded: {client_id[:8]}...")
                return client_id
        except Exception as e:
            logger.warning(f"Failed to read client_id: {e}")

    # Создаем новый client_id
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    client_id = str(uuid.uuid4())

    try:
        client_id_file.write_text(client_id, encoding="utf-8")
        logger.info(f"New client_id created: {client_id[:8]}...")
    except Exception as e:
        logger.error(f"Failed to save client_id: {e}")

    _cached_client_id = client_id
    return client_id
