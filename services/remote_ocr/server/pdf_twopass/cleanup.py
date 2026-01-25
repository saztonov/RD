"""Очистка временных файлов после обработки."""
from __future__ import annotations

import os
import shutil

from ..logging_config import get_logger
from ..manifest_models import TwoPassManifest

logger = get_logger(__name__)


def cleanup_manifest_files(manifest: TwoPassManifest) -> None:
    """Удалить все временные файлы после обработки"""
    try:
        crops_dir = manifest.crops_dir
        if os.path.exists(crops_dir):
            shutil.rmtree(crops_dir)
            logger.info(f"Удалена директория кропов: {crops_dir}")
    except Exception as e:
        logger.warning(f"Ошибка удаления кропов: {e}")
