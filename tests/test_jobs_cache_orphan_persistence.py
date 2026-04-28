"""Тест persistence orphan-set в snapshot.

Регрессия 2026-04-28: десктоп-клиент 30 часов поллил удалённую задачу
(19854 запросов /jobs/{id}/details → 404), потому что:
1. _check_auto_download не проверял is_orphan
2. snapshot не хранил orphan-set, и после рестарта «мёртвая» задача
   возвращалась в кеш и снова попадала в auto-download.
"""

import os
import pytest

# QSettings требует QApplication, поэтому работаем с PySide6 опционально
pyside6 = pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402

from app.gui.remote_ocr.jobs_cache import JobsCache  # noqa: E402
from app.gui.remote_ocr.job_persistence import (  # noqa: E402
    load_snapshot,
    save_snapshot,
)
from rd_core.dto.jobs import JobInfoDTO  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    if QCoreApplication.instance() is None:
        app = QCoreApplication([])
        yield app
    else:
        yield QCoreApplication.instance()


@pytest.fixture(autouse=True)
def _clean_snapshot_settings():
    """Очищаем snapshot-ключ перед каждым тестом."""
    settings = QSettings("PDFAnnotationTool", "RemoteOCR")
    settings.remove("remote_ocr/jobs_snapshot")
    yield
    settings.remove("remote_ocr/jobs_snapshot")


def _make_job(job_id: str, status: str = "done") -> JobInfoDTO:
    return JobInfoDTO(
        id=job_id,
        status=status,
        progress=1.0,
        document_id="doc-1",
        document_name="test.pdf",
        task_name="test",
        created_at="2026-04-28T00:00:00",
        updated_at="2026-04-28T00:00:00",
        error_message=None,
        node_id="node-1",
        status_message=None,
        priority=0,
    )


def test_save_excludes_orphan_jobs():
    cache = JobsCache()
    cache.replace_all([_make_job("a"), _make_job("b"), _make_job("c")])
    cache.mark_orphan("b")  # b выпадет из _jobs

    save_snapshot(cache)

    cache2 = JobsCache()
    load_snapshot(cache2)

    ids = {j.id for j in cache2.get_all()}
    assert ids == {"a", "c"}
    assert cache2.is_orphan("b"), "Orphan-флаг должен сохраниться после load"


def test_orphan_persisted_across_restart_blocks_re_add():
    """Сценарий из лога: задача удалена, snapshot сохранён,
    приложение перезапущено, server-delta содержит другие задачи —
    orphan не должен возвращаться в кеш через delta."""
    cache = JobsCache()
    cache.replace_all([_make_job("ghost"), _make_job("alive")])
    cache.mark_orphan("ghost")
    save_snapshot(cache)

    # Эмуляция рестарта: новый кеш, загружаем snapshot
    cache2 = JobsCache()
    load_snapshot(cache2)
    assert cache2.is_orphan("ghost")
    assert {j.id for j in cache2.get_all()} == {"alive"}


def test_load_orphans_filters_jobs_field():
    """Если в payload как-то прокрался orphan в jobs[] (старый snapshot)
    — load должен его отфильтровать."""
    cache = JobsCache()
    # Эмулируем старый snapshot вручную: jobs содержит orphan, orphans отдельно
    import json
    import time

    settings = QSettings("PDFAnnotationTool", "RemoteOCR")
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": "ghost",
                    "status": "done",
                    "progress": 1.0,
                    "document_id": "d",
                    "document_name": "x",
                    "task_name": "t",
                    "created_at": "2026",
                    "updated_at": "2026",
                    "error_message": None,
                    "node_id": "n",
                    "status_message": None,
                    "priority": 0,
                },
                {
                    "id": "alive",
                    "status": "done",
                    "progress": 1.0,
                    "document_id": "d",
                    "document_name": "x",
                    "task_name": "t",
                    "created_at": "2026",
                    "updated_at": "2026",
                    "error_message": None,
                    "node_id": "n",
                    "status_message": None,
                    "priority": 0,
                },
            ],
            "orphans": ["ghost"],
            "server_time": "2026",
            "saved_at": time.time(),
        }
    )
    settings.setValue("remote_ocr/jobs_snapshot", payload)

    load_snapshot(cache)
    assert cache.is_orphan("ghost")
    assert {j.id for j in cache.get_all()} == {"alive"}
