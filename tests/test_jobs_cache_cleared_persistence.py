"""Тест persistence cleared-set в snapshot.

Регрессия: после нажатия "Очистить все задачи" список возвращался при
перезапуске приложения, потому что snapshot не сохранял идентификаторы
очищенных задач, а серверный DELETE мог упасть/задержаться — следующий
list_jobs воскрешал их.
"""

import json
import time

import pytest

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
        created_at="2026-04-29T00:00:00",
        updated_at="2026-04-29T00:00:00",
        error_message=None,
        node_id="node-1",
        status_message=None,
        priority=0,
    )


def test_save_includes_cleared_ids():
    cache = JobsCache()
    cache.replace_all([_make_job("a"), _make_job("b")])
    cache.clear()  # маркирует {a, b} как cleared

    save_snapshot(cache)

    settings = QSettings("PDFAnnotationTool", "RemoteOCR")
    raw = settings.value("remote_ocr/jobs_snapshot")
    assert raw, "snapshot должен быть записан"
    data = json.loads(raw)
    assert set(data.get("cleared_job_ids", [])) == {"a", "b"}
    assert data.get("jobs") == []


def test_cleared_persisted_across_restart_blocks_re_add_via_delta():
    """После очистки серверный DELETE мог упасть; при следующем delta
    задачи возвращались. cleared в snapshot должен это блокировать."""
    cache = JobsCache()
    cache.replace_all([_make_job("ghost"), _make_job("survivor")])
    cache.clear()
    save_snapshot(cache)

    # Эмуляция рестарта.
    cache2 = JobsCache()
    load_snapshot(cache2)
    assert cache2.is_cleared("ghost")
    assert cache2.is_cleared("survivor")

    # Сервер возвращает их через delta — не должны попасть в кеш.
    cache2.update_delta([_make_job("ghost"), _make_job("survivor")])
    assert cache2.get_all() == []


def test_cleared_blocks_full_replace_after_restart():
    cache = JobsCache()
    cache.replace_all([_make_job("ghost")])
    cache.clear()
    save_snapshot(cache)

    cache2 = JobsCache()
    load_snapshot(cache2)
    cache2.replace_all([_make_job("ghost"), _make_job("new")])
    ids = {j.id for j in cache2.get_all()}
    assert ids == {"new"}


def test_legacy_snapshot_without_cleared_field_loads():
    """Старый snapshot без cleared_job_ids должен читаться без ошибок."""
    settings = QSettings("PDFAnnotationTool", "RemoteOCR")
    payload = json.dumps(
        {
            "jobs": [
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
            "orphans": [],
            # cleared_job_ids отсутствует
            "server_time": "2026",
            "saved_at": time.time(),
        }
    )
    settings.setValue("remote_ocr/jobs_snapshot", payload)

    cache = JobsCache()
    load_snapshot(cache)
    assert {j.id for j in cache.get_all()} == {"alive"}
    assert cache.get_cleared_ids() == set()


def test_prune_cleared_after_full_refresh_clears_set():
    """Полный refresh без cleared id → они подтверждены удалёнными
    на сервере → cleared очищается, снимок не разрастается."""
    cache = JobsCache()
    cache.replace_all([_make_job("a"), _make_job("b")])
    cache.clear()
    save_snapshot(cache)

    cache2 = JobsCache()
    load_snapshot(cache2)
    assert cache2.get_cleared_ids() == {"a", "b"}

    # Имитация полного fetch: сервер вернул пустой список.
    cache2.prune_cleared(set())
    save_snapshot(cache2)

    cache3 = JobsCache()
    load_snapshot(cache3)
    assert cache3.get_cleared_ids() == set()
