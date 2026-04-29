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

    Cleared-задачи (явно удалённые пользователем через "Очистить все задачи")
    сериализуются в `cleared_job_ids` и фильтруются при load_snapshot и в
    write-операциях кеша — чтобы они не возвращались, даже если серверный
    DELETE упал или гонка polling вернула их в delta.
    """
    try:
        orphans = cache.get_orphans()
        cleared = cache.get_cleared_ids()
        excluded = orphans | cleared
        jobs = [j for j in cache.get_all() if j.id not in excluded]
        jobs_data = [asdict(j) for j in jobs]
        payload = json.dumps({
            "jobs": jobs_data,
            "orphans": list(orphans),
            "cleared_job_ids": list(cleared),
            "server_time": cache.last_server_time or "",
            "saved_at": time.time(),
        }, ensure_ascii=False)

        settings = QSettings("PDFAnnotationTool", "RemoteOCR")
        settings.setValue(_SNAPSHOT_KEY, payload)
        logger.info(
            f"Snapshot сохранён: {len(jobs_data)} задач, "
            f"orphans={len(orphans)}, cleared={len(cleared)}"
        )
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

        # Восстанавливаем orphan/cleared ДО replace_all, чтобы UI/auto-download
        # не пытались обращаться к удалённым задачам и cleared фильтрация
        # работала уже на первой загрузке.
        orphan_ids = data.get("orphans", []) or []
        if orphan_ids:
            cache.load_orphans(orphan_ids)

        cleared_ids = data.get("cleared_job_ids", []) or []
        if cleared_ids:
            cache.load_cleared_ids(cleared_ids)

        excluded = set(orphan_ids) | set(cleared_ids)
        jobs = [
            JobInfoDTO.from_dict(j)
            for j in data.get("jobs", [])
            if j.get("id") not in excluded
        ]

        if jobs:
            cache.replace_all(jobs, data.get("server_time") or None)
            logger.info(
                f"Snapshot загружен: {len(jobs)} задач, "
                f"orphans={len(orphan_ids)}, cleared={len(cleared_ids)}, "
                f"server_time={cache.last_server_time}"
            )
        elif orphan_ids or cleared_ids:
            logger.info(
                f"Snapshot загружен: 0 задач, "
                f"orphans={len(orphan_ids)}, cleared={len(cleared_ids)}"
            )
    except Exception as e:
        logger.debug(f"Не удалось загрузить snapshot: {e}")
