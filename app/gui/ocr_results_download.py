"""Скачивание итоговых документов OCR (без crops) для узла дерева."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from app.gui.r2_node_files_dialog import _DownloadWorker
from app.tree_models import FileType

if TYPE_CHECKING:
    from app.tree_client import TreeClient, TreeNode

logger = logging.getLogger(__name__)

RESULT_FILE_TYPES = {
    FileType.PDF,
    FileType.RESULT_JSON,
    FileType.RESULT_MD,
    FileType.OCR_HTML,
}


def download_ocr_results(parent, node: "TreeNode", client: "TreeClient") -> None:
    """Скачать итоговые документы OCR для узла (без crops).

    Берёт файлы из node_files с типами PDF/RESULT_JSON/RESULT_MD/OCR_HTML
    и сохраняет их в выбранную пользователем папку.
    """
    try:
        files = client.get_node_files(node.id)
    except Exception as e:
        logger.error(f"Failed to get node_files for {node.id}: {e}")
        QMessageBox.critical(parent, "Ошибка", f"Не удалось получить список файлов:\n{e}")
        return

    results = [f for f in files if f.file_type in RESULT_FILE_TYPES and f.r2_key]
    if not results:
        QMessageBox.information(
            parent,
            "Скачивание результатов OCR",
            "Нет итоговых документов для скачивания.",
        )
        return

    dest_dir = QFileDialog.getExistingDirectory(
        parent, "Выберите папку для сохранения результатов OCR"
    )
    if not dest_dir:
        return

    subdir = os.path.join(dest_dir, _safe_name(node.name))
    os.makedirs(subdir, exist_ok=True)

    keys = [f.r2_key for f in results]

    progress = QProgressDialog(
        f"Скачивание {len(keys)} файл(ов)...", "Отмена", 0, len(keys), parent
    )
    progress.setWindowTitle("Скачивание результатов OCR")
    progress.setWindowModality(Qt.NonModal)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    thread = QThread()
    worker = _DownloadWorker(keys, subdir)
    worker.moveToThread(thread)

    state = {"ok": 0, "fail": 0}

    def _on_progress(current: int, total: int):
        if not progress.isHidden():
            progress.setValue(current)

    def _on_worker_finished(ok: int, fail: int):
        state["ok"] = ok
        state["fail"] = fail
        thread.quit()

    def _on_thread_finished():
        progress.close()
        msg = f"Скачано: {state['ok']}"
        if state["fail"]:
            msg += f"\nОшибок: {state['fail']}"
        msg += f"\n\nПапка: {subdir}"
        QTimer.singleShot(0, lambda: QMessageBox.information(parent, "Скачивание завершено", msg))
        # Очистка ссылок
        refs = getattr(parent, "_ocr_download_refs", [])
        refs[:] = [r for r in refs if r[0] is not thread]

    thread.started.connect(worker.run)
    worker.progress.connect(_on_progress)
    worker.finished.connect(_on_worker_finished)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(_on_thread_finished)
    thread.finished.connect(thread.deleteLater)
    progress.canceled.connect(worker.cancel)

    # Удерживаем ссылки чтобы GC не убил воркер/поток до завершения
    if not hasattr(parent, "_ocr_download_refs"):
        parent._ocr_download_refs = []
    parent._ocr_download_refs.append((thread, worker))

    thread.start()


def _safe_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in name).strip() or "document"
