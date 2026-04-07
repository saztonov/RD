import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, QRect, Qt, QSortFilterProxyModel
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from app.gui.remote_ocr.cancel_delegate import CancelButtonDelegate
from app.gui.remote_ocr.jobs_model import JobsTableModel
from rd_core.dto.jobs import JobInfoDTO


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _job(status: str, job_id: str = "job-1") -> JobInfoDTO:
    return JobInfoDTO(
        id=job_id,
        status=status,
        progress=0.25,
        document_id="doc-1",
        document_name="test.pdf",
        task_name="Test OCR",
    )


def _proxy_index(job: JobInfoDTO):
    model = JobsTableModel()
    model.update_jobs([job])

    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.setSortRole(Qt.UserRole)

    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 50, 28)

    return proxy, proxy.index(0, 6), option


def _mouse_release(x: int, y: int) -> QMouseEvent:
    point = QPointF(x, y)
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        point,
        point,
        point,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_cancel_delegate_emits_job_id_for_click_inside_button(qapp):
    delegate = CancelButtonDelegate()
    proxy, index, option = _proxy_index(_job("queued", "job-queued"))
    received = []
    delegate.cancel_requested.connect(received.append)

    handled = delegate.editorEvent(_mouse_release(25, 14), proxy, option, index)

    assert handled is True
    assert received == ["job-queued"]


def test_cancel_delegate_ignores_click_outside_button(qapp):
    delegate = CancelButtonDelegate()
    proxy, index, option = _proxy_index(_job("queued", "job-outside"))
    received = []
    delegate.cancel_requested.connect(received.append)

    handled = delegate.editorEvent(_mouse_release(2, 2), proxy, option, index)

    assert handled is False
    assert received == []


@pytest.mark.parametrize("status", ["done", "error", "cancelled", "draft"])
def test_cancel_delegate_rejects_non_cancellable_statuses(qapp, status):
    delegate = CancelButtonDelegate()
    proxy, index, option = _proxy_index(_job(status, f"job-{status}"))
    received = []
    delegate.cancel_requested.connect(received.append)

    handled = delegate.editorEvent(_mouse_release(25, 14), proxy, option, index)

    assert handled is False
    assert received == []
