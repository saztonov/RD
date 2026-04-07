"""Миксин создания OCR-задач для JobsController."""
from __future__ import annotations

import logging
import tempfile
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
            "datalab",
            "chandra",
        ) else "datalab"

        self._pending_output_dir = dialog.output_dir

        from app.gui.toast import show_toast

        show_toast(mw, "Отправка задачи...", duration=1500)

        logger.info(
            "Отправка задачи на сервер: engine=%s, blocks=%s, image_model=%s, "
            "stamp_model=%s, node_id=%s",
            engine,
            len(selected_blocks),
            getattr(dialog, "image_model", None),
            getattr(dialog, "stamp_model", None),
            node_id,
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

    def create_jobs_for_tree_selection(self, nodes: list) -> None:
        """Показать единый OCR-диалог и поставить выбранные документы в очередь."""
        from PySide6.QtWidgets import QDialog, QMessageBox

        from app.gui.ocr_dialog import OCRDialog
        from app.gui.toast import show_toast

        mw = self.main_window

        if not nodes:
            QMessageBox.warning(
                mw, "Ошибка", "В дереве проектов не выбраны документы для OCR"
            )
            return

        dialog = OCRDialog(
            mw,
            task_name=f"batch-{len(nodes)}-documents",
            batch_count=len(nodes),
        )
        if dialog.exec() != QDialog.Accepted:
            return

        client = self._get_client()
        if client is None:
            QMessageBox.warning(mw, "Ошибка", "Клиент не инициализирован")
            return

        engine = dialog.ocr_backend if dialog.ocr_backend in (
            "datalab",
            "chandra",
        ) else "datalab"

        document_specs = [
            {
                "node_id": node.id,
                "name": node.name,
                "r2_key": node.attributes.get("r2_key", ""),
                "is_locked": bool(node.is_locked),
            }
            for node in nodes
        ]

        self._last_output_dir = dialog.output_dir
        self._last_engine = dialog.ocr_backend
        self._pending_output_dir = dialog.output_dir

        show_toast(
            mw,
            f"Отправка {len(document_specs)} документов в очередь OCR...",
            duration=2000,
        )

        self._executor.submit(
            self._create_jobs_for_tree_selection_bg,
            client,
            document_specs,
            engine,
            getattr(dialog, "text_model", None),
            getattr(dialog, "table_model", None),
            getattr(dialog, "image_model", None),
            getattr(dialog, "stamp_model", None),
        )

    # Block helpers ---------------------------------------------------------

    def _get_selected_blocks(self) -> list:
        """Получить все блоки для OCR."""
        return self._get_document_blocks(self.main_window.annotation_document)

    def _get_document_blocks(self, document: object | None) -> list:
        """Получить все блоки OCR из переданного документа."""
        blocks = []
        if document:
            for page in getattr(document, "pages", []) or []:
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

    # Background creation ---------------------------------------------------

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
        """Фоновое создание одиночной OCR-задачи."""
        try:
            from app.ocr_client import AuthenticationError, PayloadTooLargeError, ServerError

            job_info = self._create_job_sync(
                client,
                pdf_path,
                blocks,
                task_name,
                engine,
                text_model,
                table_model,
                image_model,
                stamp_model,
                node_id=node_id,
                is_correction_mode=is_correction_mode,
                r2_key=r2_key,
                cleanup_blocks=cleanup_blocks,
                annotation_document=annotation_document,
            )

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
            logger.error("Ошибка сервера: %s", e)
            self._worker.job_create_error.emit(
                "server", f"Сервер недоступен.\n{e}"
            )
        except Exception as e:
            logger.error("Ошибка создания задачи: %s", e, exc_info=True)
            self._worker.job_create_error.emit("generic", str(e))

    def _create_jobs_for_tree_selection_bg(
        self,
        client: RemoteOCRClient,
        document_specs: list[dict],
        engine: str,
        text_model: str | None,
        table_model: str | None,
        image_model: str | None,
        stamp_model: str | None,
    ) -> None:
        """Фоновая пакетная постановка выбранных документов в OCR-очередь."""
        from app.annotation_db import AnnotationDBIO
        from app.ocr_client import AuthenticationError, PayloadTooLargeError, ServerError
        from rd_core.r2_storage import R2Storage

        summary: dict[str, list[str]] = {"queued": [], "skipped": [], "failed": []}

        try:
            r2 = R2Storage()
        except Exception as e:
            for spec in document_specs:
                summary["failed"].append(
                    f"{spec['name']}: не удалось инициализировать R2 ({e})"
                )
            self._worker.batch_finished.emit(summary)
            return

        for index, spec in enumerate(document_specs):
            node_id = spec["node_id"]
            document_name = spec["name"]
            r2_key = (spec.get("r2_key") or "").strip()

            if spec.get("is_locked"):
                summary["skipped"].append(f"{document_name}: документ заблокирован")
                continue

            if not r2_key or not r2_key.lower().endswith(".pdf"):
                summary["skipped"].append(
                    f"{document_name}: отсутствует или некорректен PDF r2_key"
                )
                continue

            try:
                annotation_document = AnnotationDBIO.load_from_db(node_id)
            except Exception as e:
                logger.error(
                    "Ошибка загрузки разметки для batch OCR: node_id=%s, error=%s",
                    node_id,
                    e,
                    exc_info=True,
                )
                summary["failed"].append(
                    f"{document_name}: не удалось загрузить разметку ({e})"
                )
                continue

            if not annotation_document:
                summary["skipped"].append(
                    f"{document_name}: нет сохраненной разметки блоков"
                )
                continue

            blocks = self._get_document_blocks(annotation_document)
            if not blocks:
                summary["skipped"].append(
                    f"{document_name}: нет блоков для распознавания"
                )
                continue

            self._clear_ocr_text_in_document(annotation_document)
            task_name = Path(document_name).stem

            try:
                with tempfile.TemporaryDirectory(prefix="rd_batch_ocr_") as temp_dir:
                    local_pdf_path = Path(temp_dir) / Path(r2_key).name
                    if not r2.download_file(r2_key, str(local_pdf_path)):
                        summary["failed"].append(
                            f"{document_name}: не удалось скачать PDF из R2"
                        )
                        continue

                    job_info = self._create_job_sync(
                        client,
                        str(local_pdf_path),
                        blocks,
                        task_name,
                        engine,
                        text_model,
                        table_model,
                        image_model,
                        stamp_model,
                        node_id=node_id,
                        is_correction_mode=False,
                        r2_key=r2_key,
                        cleanup_blocks=None,
                        annotation_document=annotation_document,
                        reuse_existing=False,
                    )
            except AuthenticationError:
                summary["failed"].append(
                    f"{document_name}: неверный API ключ Remote OCR"
                )
                for rest in document_specs[index + 1 :]:
                    summary["failed"].append(
                        f"{rest['name']}: пакет остановлен после ошибки авторизации"
                    )
                logger.error("Ошибка авторизации в пакетном OCR для %s", document_name)
                break
            except PayloadTooLargeError:
                summary["failed"].append(
                    f"{document_name}: PDF превышает лимит сервера"
                )
                continue
            except ServerError as e:
                summary["failed"].append(
                    f"{document_name}: сервер Remote OCR недоступен ({e})"
                )
                continue
            except Exception as e:
                logger.error(
                    "Ошибка пакетного OCR для node_id=%s (%s): %s",
                    node_id,
                    document_name,
                    e,
                    exc_info=True,
                )
                summary["failed"].append(f"{document_name}: {e}")
                continue

            self._worker.job_created.emit(job_info)
            summary["queued"].append(document_name)

        self._worker.batch_finished.emit(summary)

    def _create_job_sync(
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
        is_correction_mode: bool = False,
        r2_key: str | None = None,
        cleanup_blocks: list | None = None,
        annotation_document: object | None = None,
        reuse_existing: bool = True,
    ):
        """Синхронно создать OCR-задачу и очистить старые результаты."""
        from app.ocr_client import get_or_create_client_id

        if node_id and r2_key:
            try:
                from app.services.document_service import get_document_service

                svc = get_document_service()
                if not svc.check_r2_exists(r2_key):
                    raise RuntimeError(
                        "PDF не загружен в облако. Синхронизируйте документ или перезагрузите его в дерево проектов."
                    )
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning("Не удалось проверить R2: %s", e)

        client_id = get_or_create_client_id()
        logger.info(
            "Начало создания OCR-задачи: engine=%s, blocks=%s, node_id=%s",
            engine,
            len(blocks),
            node_id,
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
            reuse_existing=reuse_existing,
            node_id=node_id,
            is_correction_mode=is_correction_mode,
        )
        logger.info("Задача создана: id=%s, status=%s", job_info.id, job_info.status)

        if node_id and r2_key:
            try:
                self._clean_old_ocr_results_bg(
                    node_id,
                    r2_key,
                    blocks_to_reprocess=cleanup_blocks,
                    annotation_document=annotation_document,
                )
            except Exception as e:
                logger.warning("Post-create cleanup failed (non-fatal): %s", e)

        return job_info

    def _on_job_created(self, job_info: JobInfo) -> None:
        """Слот: задача создана на сервере."""
        logger.info(
            "Обработка job_created: job_id=%s, status=%s",
            job_info.id,
            job_info.status,
        )

        temp_job_id = getattr(job_info, "_temp_job_id", None)

        if temp_job_id:
            self._cache.remove_optimistic(temp_job_id)
            logger.info(
                "Удалена временная задача из оптимистичного списка: %s",
                temp_job_id,
            )

        self._cache.add_optimistic(job_info.id, job_info)
        logger.info(
            "Реальная задача добавлена в оптимистичный список: %s",
            job_info.id,
        )

        QTimer.singleShot(5000, self.refresh)
        self.job_created.emit(job_info)

    def _on_job_create_error(self, error_type: str, message: str) -> None:
        """Слот: ошибка создания задачи."""
        self._cache.remove_uploading_optimistic()
        self.job_create_error.emit(error_type, message)

    def _on_batch_finished(self, summary: dict) -> None:
        """Показать итоговый отчёт по пакетной постановке OCR-задач."""
        from PySide6.QtWidgets import QMessageBox

        self.refresh(force_full=True)

        message = self._format_batch_summary(summary)
        should_warn = summary.get("failed") or (
            not summary.get("queued") and summary.get("skipped")
        )
        if should_warn:
            QMessageBox.warning(self.main_window, "Пакетный OCR", message)
        else:
            QMessageBox.information(self.main_window, "Пакетный OCR", message)

    def _format_batch_summary(self, summary: dict) -> str:
        """Сформировать текст итогового отчёта для batch OCR."""
        queued = summary.get("queued", [])
        skipped = summary.get("skipped", [])
        failed = summary.get("failed", [])

        lines = [
            f"Поставлено в очередь: {len(queued)}",
            f"Пропущено: {len(skipped)}",
            f"Ошибок: {len(failed)}",
        ]

        if queued:
            lines.append("")
            lines.append("В очереди:")
            lines.extend(f"• {name}" for name in queued)

        if skipped:
            lines.append("")
            lines.append("Пропущено:")
            lines.extend(f"• {item}" for item in skipped)

        if failed:
            lines.append("")
            lines.append("Ошибки:")
            lines.extend(f"• {item}" for item in failed)

        return "\n".join(lines)

    # In-memory cleanup -----------------------------------------------------

    def _clear_ocr_text_in_memory(
        self,
        blocks_to_reprocess: list | None = None,
    ) -> int:
        """Быстрая очистка ocr_text в памяти (GUI-поток)."""
        return self._clear_ocr_text_in_document(
            self.main_window.annotation_document,
            blocks_to_reprocess=blocks_to_reprocess,
        )

    def _clear_ocr_text_in_document(
        self,
        document: object | None,
        blocks_to_reprocess: list | None = None,
    ) -> int:
        """Очистить OCR-текст у блоков в переданном документе."""
        reprocess_set = set(blocks_to_reprocess) if blocks_to_reprocess else None
        cleared = 0

        if document:
            for page in getattr(document, "pages", []) or []:
                for block in page.blocks:
                    if hasattr(block, "ocr_text") and block.ocr_text:
                        if reprocess_set is None or block.id in reprocess_set:
                            block.ocr_text = None
                            cleared += 1

        return cleared
