"""Скачивание итоговых документов OCR (без crops) для узла дерева."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from app.gui.r2_node_files_dialog import _DownloadWorker
from app.tree_models import FileType
from rd_core.r2_storage import R2Storage

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


class _BatchDownloadWorker(QObject):
    """Воркер для пакетного скачивания: принимает список (r2_key, local_path)."""

    progress = Signal(int, int)
    finished = Signal(int, int)

    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self.items = items
        self._cancelled = False

    def run(self):
        r2 = R2Storage()
        ok = 0
        fail = 0
        total = len(self.items)
        for i, (key, local_path) in enumerate(self.items):
            if self._cancelled:
                break
            try:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                if r2.download_file(key, local_path):
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                logger.error(f"Batch download failed for {key}: {e}")
                fail += 1
            self.progress.emit(i + 1, total)
        self.finished.emit(ok, fail)

    def cancel(self):
        self._cancelled = True


def download_ocr_results_batch(parent, nodes: list["TreeNode"], client: "TreeClient") -> None:
    """Пакетно скачать итоговые документы OCR для нескольких узлов."""
    if not nodes:
        return

    items: list[tuple[str, str]] = []
    skipped: list[str] = []
    errors: list[str] = []

    dest_dir = QFileDialog.getExistingDirectory(
        parent, "Выберите папку для сохранения результатов OCR"
    )
    if not dest_dir:
        return

    for node in nodes:
        try:
            files = client.get_node_files(node.id)
        except Exception as e:
            logger.error(f"Failed to get node_files for {node.id}: {e}")
            errors.append(f"{node.name}: {e}")
            continue

        results = [f for f in files if f.file_type in RESULT_FILE_TYPES and f.r2_key]
        if not results:
            skipped.append(node.name)
            continue

        subdir = os.path.join(dest_dir, _safe_name(node.name))
        for f in results:
            basename = os.path.basename(f.r2_key.replace("\\", "/"))
            items.append((f.r2_key, os.path.join(subdir, basename)))

    if not items:
        msg = "Нет итоговых документов ни у одного из выбранных документов."
        if skipped:
            msg += "\n\nПропущено: " + ", ".join(skipped)
        if errors:
            msg += "\n\nОшибки:\n" + "\n".join(errors)
        QMessageBox.information(parent, "Скачивание результатов OCR", msg)
        return

    progress = QProgressDialog(
        f"Скачивание {len(items)} файл(ов) из {len(nodes)} документов...",
        "Отмена",
        0,
        len(items),
        parent,
    )
    progress.setWindowTitle("Скачивание результатов OCR")
    progress.setWindowModality(Qt.NonModal)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    thread = QThread()
    worker = _BatchDownloadWorker(items)
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
        msg = f"Скачано файлов: {state['ok']}"
        if state["fail"]:
            msg += f"\nОшибок: {state['fail']}"
        if skipped:
            msg += f"\n\nБез результатов OCR ({len(skipped)}):\n" + ", ".join(skipped)
        if errors:
            msg += "\n\nОшибки получения списка:\n" + "\n".join(errors)
        msg += f"\n\nПапка: {dest_dir}"
        QTimer.singleShot(0, lambda: QMessageBox.information(parent, "Скачивание завершено", msg))
        refs = getattr(parent, "_ocr_download_refs", [])
        refs[:] = [r for r in refs if r[0] is not thread]

    thread.started.connect(worker.run)
    worker.progress.connect(_on_progress)
    worker.finished.connect(_on_worker_finished)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(_on_thread_finished)
    thread.finished.connect(thread.deleteLater)
    progress.canceled.connect(worker.cancel)

    if not hasattr(parent, "_ocr_download_refs"):
        parent._ocr_download_refs = []
    parent._ocr_download_refs.append((thread, worker))

    thread.start()


def _safe_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in name).strip() or "document"
