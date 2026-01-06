"""Воркер для удаления файлов с R2"""
import logging
from typing import Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class R2DeleteWorker(QThread):
    """Воркер для удаления файлов с R2"""

    progress = Signal(int, int, str)
    finished = Signal(bool, str, list)  # success, message, deleted_keys

    def __init__(self, files_to_delete: list, node_id: Optional[str] = None):
        super().__init__()
        self.files_to_delete = files_to_delete
        self.node_id = node_id
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from rd_core.r2_storage import R2Storage

        try:
            r2 = R2Storage()
            total = len(self.files_to_delete)

            keys_to_delete = []
            for file_info in self.files_to_delete:
                r2_key = file_info.get("path", "")
                if r2_key:
                    keys_to_delete.append(r2_key)

            if not keys_to_delete:
                self.finished.emit(False, "Нет файлов для удаления", [])
                return

            batch_size = 1000
            all_deleted = []
            all_errors = []

            for i in range(0, len(keys_to_delete), batch_size):
                if self._cancelled:
                    self.finished.emit(False, "Отменено", all_deleted)
                    return

                batch = keys_to_delete[i : i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(keys_to_delete) + batch_size - 1) // batch_size

                progress_msg = (
                    f"Пакет {batch_num}/{total_batches} ({len(batch)} файлов)"
                )
                self.progress.emit(i + len(batch), total, progress_msg)

                deleted, errors = r2.delete_objects_batch(batch)
                all_deleted.extend(deleted)
                all_errors.extend(errors)

            if all_errors:
                error_msg = (
                    f"Удалено {len(all_deleted)}/{total} файлов. "
                    f"Ошибок: {len(all_errors)}"
                )
                self.finished.emit(False, error_msg, all_deleted)
            else:
                self.finished.emit(
                    True, f"Удалено {len(all_deleted)}/{total} файлов", all_deleted
                )

        except Exception as e:
            logger.error(f"Delete failed: {e}")
            self.finished.emit(False, str(e), [])
