"""Download orchestrator для OCR результатов.

Управляет скачиванием файлов из R2 и auto-download логикой.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from app.gui.remote_ocr.jobs_cache import JobsCache
    from app.ocr_client import RemoteOCRClient

logger = logging.getLogger(__name__)


class DownloadOrchestrator(QObject):
    """Оркестрация скачивания OCR результатов из R2."""

    # Worker signals (из background thread)
    download_started = Signal(str, int)
    download_progress = Signal(str, int, str)
    download_finished = Signal(str, str)
    download_error = Signal(str, str)

    def __init__(self, cache: JobsCache, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache = cache

    # ── Public API ───────────────────────────────────────────────────

    def auto_download(
        self,
        job_id: str,
        client: RemoteOCRClient,
        extract_dir: str,
    ) -> bool:
        """Подготовить auto-download. Возвращает True если запущен."""
        if self._cache.is_downloading(job_id):
            logger.debug(f"Download already in progress: {job_id}")
            return False

        self._cache.mark_downloading(job_id)
        return True

    def download_bg(
        self,
        job_id: str,
        client: Optional[RemoteOCRClient],
        extract_dir: str,
        pdf_stem: str,
    ) -> None:
        """Фоновое скачивание результата (вызывается из ThreadPoolExecutor)."""
        try:
            # Получаем r2_prefix
            job_details = client.get_job_details(job_id) if client else {}
            r2_prefix = job_details.get("r2_prefix")

            if not r2_prefix:
                logger.warning(f"Задача {job_id} не имеет r2_prefix")
                self._cache.unmark_downloading(job_id)
                return

            self._download_files(job_id, job_details, r2_prefix, extract_dir, pdf_stem)
        except Exception as e:
            logger.error(f"Ошибка подготовки скачивания {job_id}: {e}")
            self._cache.unmark_downloading(job_id)

    def download_with_prefix_bg(
        self,
        job_id: str,
        client: Optional[RemoteOCRClient],
        r2_prefix: str,
        extract_dir: str,
        pdf_stem: str,
    ) -> None:
        """Фоновое скачивание с известным r2_prefix."""
        try:
            job_details = client.get_job_details(job_id) if client else {}
            self._download_files(job_id, job_details, r2_prefix, extract_dir, pdf_stem)
        except Exception as e:
            logger.error(f"Ошибка скачивания {job_id}: {e}")
            self.download_error.emit(job_id, str(e))

    def check_auto_download(
        self,
        jobs: list,
        current_node_id: Optional[str],
        current_doc: object | None,
    ) -> Optional[str]:
        """Проверить нужен ли auto-download. Возвращает job_id или None."""
        if not current_node_id:
            return None

        has_active = any(
            j.status in ("queued", "processing")
            and getattr(j, "node_id", None) == current_node_id
            for j in jobs
        )
        if has_active:
            return None

        latest_done = None
        for job in reversed(jobs):
            if (
                job.status in ("done", "partial")
                and getattr(job, "node_id", None) == current_node_id
                and not self._cache.is_downloaded(job.id)
                and not self._cache.is_downloading(job.id)
            ):
                latest_done = job
                break

        if latest_done is None:
            return None

        # Пропускаем если все блоки уже распознаны
        if current_doc:
            all_blocks = [b for p in current_doc.pages for b in p.blocks]
            if all_blocks and all(b.ocr_text for b in all_blocks):
                self._cache.mark_downloaded(latest_done.id)
                return None

        return latest_done.id

    # ── Private ──────────────────────────────────────────────────────

    def _download_files(
        self,
        job_id: str,
        job_details: dict,
        r2_prefix: str,
        extract_dir: str,
        pdf_stem: str,
    ) -> None:
        """Скачать файлы результата из R2."""
        try:
            from rd_core.r2_metadata_cache import get_metadata_cache
            from rd_core.r2_storage import R2Storage

            r2 = R2Storage()
            extract_path = Path(extract_dir)
            extract_path.mkdir(parents=True, exist_ok=True)

            doc_name = job_details.get("document_name", "result.pdf")
            doc_stem = Path(doc_name).stem
            actual_prefix = job_details.get("result_prefix") or r2_prefix

            get_metadata_cache().invalidate_prefix(actual_prefix + "/")

            files_to_download = [
                (f"{doc_stem}_annotation.json", f"{pdf_stem}_annotation.json"),
                (f"{doc_stem}_ocr.html", f"{pdf_stem}_ocr.html"),
                (f"{doc_stem}_result.json", f"{pdf_stem}_result.json"),
                (f"{doc_stem}_document.md", f"{pdf_stem}_document.md"),
            ]

            self.download_started.emit(job_id, len(files_to_download))

            for idx, (remote_name, local_name) in enumerate(files_to_download, 1):
                self.download_progress.emit(job_id, idx, local_name)
                remote_key = f"{actual_prefix}/{remote_name}"
                local_path = extract_path / local_name
                try:
                    if r2.exists(remote_key, use_cache=False):
                        r2.download_file(remote_key, str(local_path), use_cache=False)
                        logger.info(f"Скачан: {local_path}")
                    else:
                        logger.warning(f"Файл не найден: {remote_key}")
                except Exception as e:
                    logger.warning(f"Не удалось скачать {remote_key}: {e}")

            logger.info(f"Результат скачан: {extract_dir}")
            self.download_finished.emit(job_id, extract_dir)

        except Exception as e:
            logger.error(f"Ошибка скачивания {job_id}: {e}")
            self.download_error.emit(job_id, str(e))
