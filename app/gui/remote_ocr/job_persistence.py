"""Snapshot persistence для OCR задач.

Сохраняет/загружает кеш задач из QSettings для мгновенного старта UI.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings

from rd_core.dto.jobs import JobInfoDTO

if TYPE_CHECKING:
    from app.gui.remote_ocr.jobs_cache import JobsCache

logger = logging.getLogger(__name__)

_SNAPSHOT_KEY = "remote_ocr/jobs_snapshot"
_SNAPSHOT_MAX_AGE = 86400  # 24 hours


def save_snapshot(cache: JobsCache) -> None:
    """Сохранить текущий кеш задач в QSettings.

    Orphan-задачи (удалённые с сервера, но кеш ещё не очищен) исключаются из
    основного списка `jobs`, но их id сохраняются отдельно в `orphans`. Без
    этого после рестарта приложения «мёртвые» задачи возвращались бы из
    snapshot'а и снова инициировали auto-download → 404 → loop.
    """
    try:
        orphans = cache.get_orphans()
        jobs = [j for j in cache.get_all() if j.id not in orphans]
        jobs_data = [asdict(j) for j in jobs]
        payload = json.dumps({
            "jobs": jobs_data,
            "orphans": list(orphans),
            "server_time": cache.last_server_time or "",
            "saved_at": time.time(),
        }, ensure_ascii=False)

        settings = QSettings("PDFAnnotationTool", "RemoteOCR")
        settings.setValue(_SNAPSHOT_KEY, payload)
        logger.info(f"Snapshot сохранён: {len(jobs_data)} задач, orphans={len(orphans)}")
    except Exception as e:
        logger.debug(f"Не удалось сохранить snapshot: {e}")


def load_snapshot(cache: JobsCache) -> None:
    """Загрузить snapshot из QSettings в кеш."""
    try:
        settings = QSettings("PDFAnnotationTool", "RemoteOCR")
        raw = settings.value(_SNAPSHOT_KEY)
        if not raw:
            return

        data = json.loads(raw)
        saved_at = data.get("saved_at", 0)

        if time.time() - saved_at > _SNAPSHOT_MAX_AGE:
            logger.debug("Snapshot слишком старый, пропускаем")
            return

        # Восстанавливаем orphan-set ДО replace_all, чтобы UI/auto-download
        # не пытались обращаться к удалённым задачам.
        orphan_ids = data.get("orphans", []) or []
        if orphan_ids:
            cache.load_orphans(orphan_ids)

        jobs = [
            JobInfoDTO.from_dict(j)
            for j in data.get("jobs", [])
            if j.get("id") not in orphan_ids
        ]

        if jobs:
            cache.replace_all(jobs, data.get("server_time") or None)
            logger.info(
                f"Snapshot загружен: {len(jobs)} задач, orphans={len(orphan_ids)}, "
                f"server_time={cache.last_server_time}"
            )
        elif orphan_ids:
            logger.info(f"Snapshot загружен: 0 задач, orphans={len(orphan_ids)}")
    except Exception as e:
        logger.debug(f"Не удалось загрузить snapshot: {e}")
