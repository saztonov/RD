"""Миксин создания OCR задач для JobsController."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

if TYPE_CHECKING:
    from app.ocr_client import RemoteOCRClient

from rd_core.dto.jobs import JobInfoDTO as JobInfo

logger = logging.getLogger(__name__)


class JobsControllerCreateMixin:
    """Создание задач: диалог, выбор блоков, smart-режим, фоновая отправка."""

    def create_job(self) -> None:
        """Показать диалог создания задачи и отправить на сервер."""
        from PySide6.QtWidgets import QDialog, QMessageBox

        from app.gui.ocr_dialog import OCRDialog

        mw = self.main_window

        if not mw.pdf_document or not mw.annotation_document:
            QMessageBox.warning(mw, "Ошибка", "Откройте PDF документ")
            return

        if getattr(mw, "_current_node_locked", False):
            QMessageBox.warning(
                mw,
                "Документ заблокирован",
                "Этот документ заблокирован от изменений.\nСначала снимите блокировку.",
            )
            return

        pdf_path = mw.annotation_document.pdf_path
        if not pdf_path or not Path(pdf_path).exists():
            if getattr(mw, "_current_pdf_path", None):
                pdf_path = mw._current_pdf_path
                mw.annotation_document.pdf_path = pdf_path

        if not pdf_path or not Path(pdf_path).exists():
            QMessageBox.warning(mw, "Ошибка", "PDF файл не найден")
            return

        node_id = getattr(mw, "_current_node_id", None) or None
        r2_key = getattr(mw, "_current_r2_key", None) or None

        task_name = Path(pdf_path).stem if pdf_path else ""
        dialog = OCRDialog(mw, task_name=task_name, pdf_path=pdf_path)
        if dialog.exec() != QDialog.Accepted:
            return

        self._last_output_dir = dialog.output_dir
        self._last_engine = dialog.ocr_backend

        all_blocks = self._get_selected_blocks()
        if not all_blocks:
            QMessageBox.warning(mw, "Ошибка", "Нет блоков для распознавания")
            return

        blocks_needing = self._get_blocks_needing_ocr()
        has_previous = len(all_blocks) > len(blocks_needing)

        if has_previous and blocks_needing:
            from app.gui.smart_ocr_mode_dialog import SmartOCRModeDialog

            mode_dialog = SmartOCRModeDialog(
                mw,
                total_count=len(all_blocks),
                needs_ocr_count=len(blocks_needing),
                successful_count=len(all_blocks) - len(blocks_needing),
            )
            if mode_dialog.exec() != QDialog.Accepted:
                return

            if mode_dialog.selected_mode == SmartOCRModeDialog.MODE_SMART:
                selected_blocks = blocks_needing
                self._is_correction_mode = True
                cleanup_blocks = [b.id for b in selected_blocks]
                self._clear_ocr_text_in_memory(blocks_to_reprocess=cleanup_blocks)
            else:
                selected_blocks = all_blocks
                self._is_correction_mode = False
                cleanup_blocks = None
                self._clear_ocr_text_in_memory()

        elif has_previous and not blocks_needing:
            QMessageBox.information(
                mw,
                "Все распознано",
                "Все блоки уже успешно распознаны.\n"
                "Добавьте новые блоки или пометьте для корректировки.",
            )
            return
        else:
            selected_blocks = all_blocks
            self._is_correction_mode = False
            cleanup_blocks = None
            self._clear_ocr_text_in_memory()

        client = self._get_client()
        if client is None:
            QMessageBox.warning(mw, "Ошибка", "Клиент не инициализирован")
            return

        engine = dialog.ocr_backend if dialog.ocr_backend in (
            "datalab", "chandra"
        ) else "datalab"

        self._pending_output_dir = dialog.output_dir

        from app.gui.toast import show_toast

        show_toast(mw, "Отправка задачи...", duration=1500)

        logger.info(
            f"Отправка задачи на сервер: engine={engine}, blocks={len(selected_blocks)}, "
            f"image_model={getattr(dialog, 'image_model', None)}, "
            f"stamp_model={getattr(dialog, 'stamp_model', None)}, node_id={node_id}"
        )

        temp_job_id = f"uploading-{uuid.uuid4().hex[:12]}"

        from app.ocr_client import JobInfo as OcrJobInfo

        temp_job = OcrJobInfo(
            id=temp_job_id,
            status="uploading",
            progress=0.0,
            document_id="",
            document_name=Path(pdf_path).name,
            task_name=task_name,
            status_message="Загрузка на сервер...",
        )
        self.job_uploading.emit(temp_job)

        annotation_doc = mw.annotation_document

        self._executor.submit(
            self._create_job_bg,
            client,
            pdf_path,
            selected_blocks,
            task_name,
            engine,
            getattr(dialog, "text_model", None),
            getattr(dialog, "table_model", None),
            getattr(dialog, "image_model", None),
            getattr(dialog, "stamp_model", None),
            node_id,
            temp_job_id,
            self._is_correction_mode,
            r2_key,
            cleanup_blocks,
            annotation_doc,
        )

    # ── Block helpers ─────────────────────────────────────────────────

    def _get_selected_blocks(self) -> list:
        """Получить все блоки для OCR."""
        blocks = []
        if self.main_window.annotation_document:
            for page in self.main_window.annotation_document.pages:
                if page.blocks:
                    blocks.extend(page.blocks)
        self._attach_prompts_to_blocks(blocks)
        return blocks

    def _get_blocks_needing_ocr(self) -> list:
        """Получить только блоки, нуждающиеся в OCR."""
        from rd_core.ocr_block_status import needs_ocr

        blocks = []
        if self.main_window.annotation_document:
            for page in self.main_window.annotation_document.pages:
                for block in page.blocks or []:
                    if needs_ocr(block):
                        blocks.append(block)
        self._attach_prompts_to_blocks(blocks)
        return blocks

    def _attach_prompts_to_blocks(self, blocks: list) -> None:
        """Промпты берутся из категорий в Supabase на стороне сервера."""
        pass

    # ── Background creation ───────────────────────────────────────────

    def _create_job_bg(
        self,
        client: RemoteOCRClient,
        pdf_path: str,
        blocks: list,
        task_name: str,
        engine: str,
        text_model: str | None,
        table_model: str | None,
        image_model: str | None,
        stamp_model: str | None,
        node_id: str | None = None,
        temp_job_id: str | None = None,
        is_correction_mode: bool = False,
        r2_key: str | None = None,
        cleanup_blocks: list | None = None,
        annotation_document: object | None = None,
    ) -> None:
        """Фоновое создание задачи."""
        try:
            from app.ocr_client import (
                AuthenticationError,
                PayloadTooLargeError,
                ServerError,
                get_or_create_client_id,
            )

            # 1. Проверка наличия PDF в R2
            if node_id and r2_key:
                try:
                    from app.services.document_service import get_document_service
                    svc = get_document_service()
                    if not svc.check_r2_exists(r2_key):
                        self._worker.job_create_error.emit(
                            "r2",
                            "PDF не загружен в облако.\n"
                            "Синхронизируйте документ или перезагрузите его "
                            "в дерево проектов.",
                        )
                        return
                except Exception as e:
                    logger.warning(f"Не удалось проверить R2: {e}")

            # 2. Отправка задачи на сервер
            client_id = get_or_create_client_id()
            logger.info(
                f"Начало создания задачи: engine={engine}, blocks={len(blocks)}"
            )
            job_info = client.create_job(
                pdf_path,
                blocks,
                client_id=client_id,
                task_name=task_name,
                engine=engine,
                text_model=text_model,
                table_model=table_model,
                image_model=image_model,
                stamp_model=stamp_model,
                node_id=node_id,
                is_correction_mode=is_correction_mode,
            )
            logger.info(f"Задача создана: id={job_info.id}, status={job_info.status}")

            # 3. Cleanup старых результатов
            if node_id and r2_key:
                try:
                    self._clean_old_ocr_results_bg(
                        node_id,
                        r2_key,
                        blocks_to_reprocess=cleanup_blocks,
                        annotation_document=annotation_document,
                    )
                except Exception as e:
                    logger.warning(f"Post-create cleanup failed (non-fatal): {e}")

            job_info._temp_job_id = temp_job_id
            self._worker.job_created.emit(job_info)
        except AuthenticationError:
            logger.error("Ошибка авторизации при создании задачи")
            self._worker.job_create_error.emit("auth", "Неверный API ключ.")
        except PayloadTooLargeError:
            logger.error("PDF файл слишком большой")
            self._worker.job_create_error.emit(
                "size", "PDF файл превышает лимит сервера."
            )
        except ServerError as e:
            logger.error(f"Ошибка сервера: {e}")
            self._worker.job_create_error.emit("server", f"Сервер недоступен.\n{e}")
        except Exception as e:
            logger.error(f"Ошибка создания задачи: {e}", exc_info=True)
            self._worker.job_create_error.emit("generic", str(e))

    def _on_job_created(self, job_info: JobInfo) -> None:
        """Слот: задача создана на сервере."""
        logger.info(
            f"Обработка job_created: job_id={job_info.id}, status={job_info.status}"
        )

        temp_job_id = getattr(job_info, "_temp_job_id", None)

        if temp_job_id:
            self._cache.remove_optimistic(temp_job_id)
            logger.info(
                f"Удалена временная задача из оптимистичного списка: {temp_job_id}"
            )

        self._cache.add_optimistic(job_info.id, job_info)
        logger.info(
            f"Реальная задача добавлена в оптимистичный список: {job_info.id}"
        )

        QTimer.singleShot(5000, self.refresh)
        self.job_created.emit(job_info)

    def _on_job_create_error(self, error_type: str, message: str) -> None:
        """Слот: ошибка создания задачи."""
        self._cache.remove_uploading_optimistic()
        self.job_create_error.emit(error_type, message)

    # ── In-memory cleanup ─────────────────────────────────────────────

    def _clear_ocr_text_in_memory(
        self,
        blocks_to_reprocess: list | None = None,
    ) -> int:
        """Быстрая очистка ocr_text в памяти (GUI-поток)."""
        reprocess_set = set(blocks_to_reprocess) if blocks_to_reprocess else None
        cleared = 0
        if self.main_window.annotation_document:
            for page in self.main_window.annotation_document.pages:
                for block in page.blocks:
                    if hasattr(block, "ocr_text") and block.ocr_text:
                        if reprocess_set is None or block.id in reprocess_set:
                            block.ocr_text = None
                            cleared += 1
        return cleared
