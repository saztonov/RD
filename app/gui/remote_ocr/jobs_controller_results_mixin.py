"""Миксин download и обработки результатов для JobsController."""
from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ocr_client import RemoteOCRClient

logger = logging.getLogger(__name__)


class JobsControllerResultsMixin:
    """Download результатов, reload annotation, refresh tree, cleanup."""

    def auto_download_result(self, job_id: str) -> None:
        """Запустить скачивание результата из R2."""
        if self._cache.is_downloading(job_id):
            logger.debug(f"Download already in progress: {job_id}")
            return

        client = self._get_client()
        if client is None:
            return

        pdf_path = getattr(self.main_window, "_current_pdf_path", None)
        if not pdf_path:
            logger.warning(
                f"Нет открытого документа для сохранения результатов job {job_id}"
            )
            return

        self._cache.mark_downloading(job_id)
        extract_dir = str(Path(pdf_path).parent)

        self._executor.submit(
            self._auto_download_bg, client, job_id, extract_dir
        )

    def _auto_download_bg(
        self, client: RemoteOCRClient, job_id: str, extract_dir: str
    ) -> None:
        """Фоновая подготовка и запуск скачивания."""
        try:
            job_details = client.get_job_details(job_id)
            r2_prefix = job_details.get("r2_prefix")

            if not r2_prefix:
                logger.warning(f"Задача {job_id} не имеет r2_prefix")
                self._cache.unmark_downloading(job_id)
                return

            self._download_result_bg(job_id, r2_prefix, extract_dir)
        except Exception as e:
            logger.error(f"Ошибка подготовки скачивания {job_id}: {e}")
            self._cache.unmark_downloading(job_id)

    def mark_node_downloads_complete(self, node_id: str) -> None:
        """Пометить done-джобы для node как скачанные."""
        self._cache.mark_node_downloads_complete(node_id)

    # ── Background download ───────────────────────────────────────────

    def _download_result_bg(
        self, job_id: str, r2_prefix: str, extract_dir: str
    ) -> None:
        """Фоновое скачивание результата в папку текущего документа."""
        try:
            from rd_core.r2_metadata_cache import get_metadata_cache
            from rd_core.r2_storage import R2Storage

            r2 = R2Storage()

            extract_path = Path(extract_dir)
            extract_path.mkdir(parents=True, exist_ok=True)

            client = self._get_client()
            job_details = client.get_job_details(job_id) if client else {}
            doc_name = job_details.get("document_name", "result.pdf")
            doc_stem = Path(doc_name).stem

            pdf_path = getattr(self.main_window, "_current_pdf_path", None)
            pdf_stem = Path(pdf_path).stem if pdf_path else doc_stem

            actual_prefix = job_details.get("result_prefix") or r2_prefix

            get_metadata_cache().invalidate_prefix(actual_prefix + "/")
            logger.debug(f"Invalidated metadata cache for prefix: {actual_prefix}/")

            files_to_download = [
                (f"{doc_stem}_annotation.json", f"{pdf_stem}_annotation.json"),
                (f"{doc_stem}_ocr.html", f"{pdf_stem}_ocr.html"),
                (f"{doc_stem}_result.json", f"{pdf_stem}_result.json"),
                (f"{doc_stem}_document.md", f"{pdf_stem}_document.md"),
            ]

            self._worker.download_started.emit(job_id, len(files_to_download))

            for idx, (remote_name, local_name) in enumerate(files_to_download, 1):
                self._worker.download_progress.emit(job_id, idx, local_name)
                remote_key = f"{actual_prefix}/{remote_name}"
                local_path = extract_path / local_name
                try:
                    if r2.exists(remote_key, use_cache=False):
                        r2.download_file(remote_key, str(local_path))
                        logger.info(f"Скачан: {local_path}")
                    else:
                        logger.warning(f"Файл не найден: {remote_key}")
                except Exception as e:
                    logger.warning(f"Не удалось скачать {remote_key}: {e}")

            logger.info(f"Результат скачан: {extract_dir}")
            self._worker.download_finished.emit(job_id, extract_dir)

        except Exception as e:
            logger.error(f"Ошибка скачивания {job_id}: {e}")
            self._worker.download_error.emit(job_id, str(e))

    # ── Download signal handlers ──────────────────────────────────────

    def _on_download_started(self, job_id: str, total_files: int) -> None:
        self.download_started.emit(job_id, total_files)

    def _on_download_progress(self, job_id: str, current: int, filename: str) -> None:
        self.download_progress.emit(job_id, current, filename)

    def _on_download_finished(self, job_id: str, extract_dir: str) -> None:
        """Слот: скачивание завершено."""
        self._cache.mark_downloaded(job_id)
        self._cache.unmark_downloading(job_id)

        self._reload_annotation_from_result(extract_dir)
        self._refresh_document_in_tree()
        self.update_ocr_stats()

        self.download_finished.emit(job_id, extract_dir)

    def _on_download_error(self, job_id: str, error_msg: str) -> None:
        self._cache.unmark_downloading(job_id)
        self.download_error.emit(job_id, error_msg)

    # ── Result handling ───────────────────────────────────────────────

    def _refresh_document_in_tree(self) -> None:
        """Обновить узел документа в дереве проектов."""
        from PySide6.QtCore import Qt

        node_id = getattr(self.main_window, "_current_node_id", None)
        if not node_id:
            return

        if not hasattr(self.main_window, "project_tree_widget"):
            return

        tree = self.main_window.project_tree_widget
        item = tree._node_map.get(node_id)
        if not item:
            return

        node = item.data(0, Qt.UserRole)
        if not node:
            return

        try:
            from rd_core.r2_metadata_cache import get_metadata_cache

            r2_key = getattr(node, "r2_key", None)
            if r2_key:
                prefix = str(PurePosixPath(r2_key).parent) + "/"
                get_metadata_cache().invalidate_prefix(prefix)
                logger.debug(f"Invalidated R2 metadata cache for prefix: {prefix}")
        except Exception as e:
            logger.warning(f"Failed to invalidate R2 metadata cache: {e}")

        logger.info(f"Refreshed document in tree: {node_id}")

    def _reload_annotation_from_result(self, extract_dir: str) -> None:
        """Обновить ocr_text в блоках из результата OCR."""
        try:
            pdf_path = getattr(self.main_window, "_current_pdf_path", None)
            if not pdf_path:
                return

            pdf_stem = Path(pdf_path).stem
            ann_path = Path(extract_dir) / f"{pdf_stem}_annotation.json"

            if not ann_path.exists():
                logger.warning(f"Файл аннотации не найден: {ann_path}")
                return

            from rd_core.annotation_io import AnnotationIO

            loaded_doc, result = AnnotationIO.load_and_migrate(str(ann_path))

            if not result.success or not loaded_doc:
                logger.warning(f"Не удалось загрузить OCR результат: {result.errors}")
                return

            current_doc = self.main_window.annotation_document
            if not current_doc:
                return

            ocr_results = {}
            for page in loaded_doc.pages:
                for block in page.blocks:
                    if block.ocr_text:
                        ocr_results[block.id] = block.ocr_text

            updated_count = 0
            for page in current_doc.pages:
                for block in page.blocks:
                    if block.id in ocr_results:
                        block.ocr_text = ocr_results[block.id]
                        if block.is_correction:
                            block.is_correction = False
                        updated_count += 1

            self.main_window._render_current_page()
            if (
                hasattr(self.main_window, "blocks_tree_manager")
                and self.main_window.blocks_tree_manager
            ):
                self.main_window.blocks_tree_manager.update_blocks_tree()

            if updated_count > 0:
                self.main_window._auto_save_annotation()

            if hasattr(self.main_window, "_load_ocr_result_file"):
                self.main_window._load_ocr_result_file()

            for preview_attr in ("ocr_preview", "ocr_preview_inline"):
                preview = getattr(self.main_window, preview_attr, None)
                if preview and getattr(preview, "_current_block_id", None):
                    preview.show_block(preview._current_block_id)

            logger.info(f"OCR результаты применены: {updated_count} блоков обновлено")
        except Exception as e:
            logger.error(f"Ошибка применения OCR результатов: {e}")

    # ── Clean old OCR results ─────────────────────────────────────────

    def _clean_old_ocr_results_bg(
        self,
        node_id: str,
        r2_key: str,
        blocks_to_reprocess: list | None = None,
        annotation_document: object | None = None,
    ) -> None:
        """Очистить старые результаты OCR (background-поток)."""
        is_smart_mode = blocks_to_reprocess is not None

        try:
            from rd_core.r2_storage import R2Storage

            r2 = R2Storage()
            pdf_stem = Path(r2_key).stem
            r2_prefix = str(PurePosixPath(r2_key).parent)

            if not is_smart_mode:
                crops_prefix = f"{r2_prefix}/crops/{pdf_stem}/"
                crop_keys = r2.list_files(crops_prefix)

                if crop_keys:
                    deleted_keys, errors = r2.delete_objects_batch(crop_keys)
                    logger.debug(f"Deleted {len(deleted_keys)} crops from R2")
                    if errors:
                        logger.warning(
                            f"Failed to delete {len(errors)} crops from R2"
                        )

                from app.tree_client import FileType, TreeClient

                client = TreeClient()
                node_files = client.get_node_files(node_id)
                for nf in node_files:
                    if nf.file_type == FileType.CROP:
                        client.delete_node_file(nf.id)

            if annotation_document:
                from app.annotation_db import AnnotationDBIO

                success = AnnotationDBIO.save_to_db(annotation_document, node_id)
                if success:
                    logger.debug(
                        f"Saved cleared annotation to Supabase: {node_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to save annotation to Supabase: {node_id}"
                    )

            mode_str = (
                f"smart ({len(blocks_to_reprocess)} blocks)"
                if is_smart_mode
                else "full"
            )
            logger.info(
                f"Cleaned old OCR results for node: {node_id} (mode={mode_str})"
            )

            self._cache.reset_node_downloads(node_id)

        except Exception as e:
            logger.warning(f"Failed to clean old OCR results: {e}")
