"""Утилиты для OCR клиента."""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Кэшированный client_id
_cached_client_id: Optional[str] = None


def get_or_create_client_id() -> str:
    """
    Получить или создать идентификатор клиента.

    Читает из ~/.config/CoreStructure/client_id.txt или генерирует новый UUID.
    Результат кэшируется в памяти для повторных вызовов.

    Returns:
        str: Уникальный идентификатор клиента
    """
    global _cached_client_id
    if _cached_client_id:
        return _cached_client_id

    # Определяем путь к файлу
    if os.name == "nt":
        config_dir = Path.home() / ".config" / "CoreStructure"
    else:
        config_dir = Path.home() / ".config" / "CoreStructure"

    client_id_file = config_dir / "client_id.txt"

    # Пытаемся прочитать существующий
    if client_id_file.exists():
        try:
            client_id = client_id_file.read_text(encoding="utf-8").strip()
            if client_id:
                _cached_client_id = client_id
                logger.info(f"Client ID loaded from {client_id_file}")
                return client_id
        except Exception as e:
            logger.warning(f"Failed to read client_id file: {e}")

    # Генерируем новый
    client_id = str(uuid.uuid4())

    # Сохраняем
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        client_id_file.write_text(client_id, encoding="utf-8")
        logger.info(f"New client ID generated and saved to {client_id_file}")
    except Exception as e:
        logger.warning(f"Failed to save client_id file: {e}")

    _cached_client_id = client_id
    return client_id


def hash_pdf(path: str) -> str:
    """Вычислить SHA256 хеш PDF файла."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
