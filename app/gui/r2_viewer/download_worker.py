"""Воркер для скачивания файлов с R2"""
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class R2DownloadWorker(QThread):
    """Воркер для параллельного скачивания файлов с R2"""

    progress = Signal(int, int, str)  # current, total, filename
    finished = Signal(bool, str)  # success, message

    def __init__(self, files_to_download: list, target_dir: Path, max_workers: int = 8):
        super().__init__()
        self.files_to_download = files_to_download
        self.target_dir = target_dir
        self.max_workers = max_workers
        self._cancelled = False
        self._downloaded = 0
        self._lock = threading.Lock()

    def cancel(self):
        self._cancelled = True

    def _download_single_file(self, file_info: dict, r2) -> bool:
        """Скачать один файл (вызывается в отдельном потоке)"""
        if self._cancelled:
            return False

        try:
            r2_key = file_info.get("path", "")
            filename = file_info.get("name", Path(r2_key).name)

            rel_path = file_info.get("rel_path", filename)
            local_path = self.target_dir / rel_path
            local_path.parent.mkdir(parents=True, exist_ok=True)

            success = r2.download_file(r2_key, str(local_path))

            with self._lock:
                if success:
                    self._downloaded += 1
                current = self._downloaded

            self.progress.emit(current, len(self.files_to_download), filename)

            return success

        except Exception as e:
            logger.error(f"Failed to download {file_info.get('path')}: {e}")
            return False

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from rd_core.r2_storage import R2Storage

        try:
            r2 = R2Storage()
            total = len(self.files_to_download)
            self._downloaded = 0
            failed = 0

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(
                        self._download_single_file, file_info, r2
                    ): file_info
                    for file_info in self.files_to_download
                }

                for future in as_completed(futures):
                    if self._cancelled:
                        for f in futures:
                            f.cancel()
                        self.finished.emit(False, "Отменено")
                        return

                    try:
                        success = future.result()
                        if not success:
                            failed += 1
                    except Exception as e:
                        logger.error(f"Download task failed: {e}")
                        failed += 1

            if failed > 0:
                msg = f"Скачано {self._downloaded}/{total} файлов (ошибок: {failed})"
                self.finished.emit(False, msg)
            else:
                msg = f"Скачано {self._downloaded}/{total} файлов"
                self.finished.emit(True, msg)

        except Exception as e:
            logger.error(f"Download failed: {e}")
            self.finished.emit(False, str(e))
