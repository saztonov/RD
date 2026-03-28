"""
Миксин для работы с файлами (открытие, сохранение, загрузка)
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.gui.file_auto_save import FileAutoSaveMixin
from app.gui.file_download import FileDownloadMixin
from app.services.document_service import get_document_service
from rd_core.annotation_canonicalizer import (
    canonicalize_annotation_document,
    get_pdf_preview_page_sizes,
)
from rd_core.annotation_io import AnnotationIO
from rd_core.models import Document, Page
from rd_core.pdf_utils import PDFDocument

logger = logging.getLogger(__name__)

# Импорт метаданных продукта
try:
    from _metadata import __product__
except ImportError:
    __product__ = "Core Structure"


class FileOperationsMixin(FileAutoSaveMixin, FileDownloadMixin):
    """Миксин для операций с файлами"""

    def _canonicalize_loaded_annotation(self, pdf_path: str):
        """Align annotation geometry with the actual preview sizes of the opened PDF."""
        if not self.annotation_document or not self.pdf_document:
            return

        try:
            page_sizes = get_pdf_preview_page_sizes(self.pdf_document)
            prefer_coords_px = bool(
                getattr(self.annotation_document, "_prefer_coords_px", False)
            )
            result = canonicalize_annotation_document(
                self.annotation_document,
                pdf_path=pdf_path,
                pdf_page_sizes=page_sizes,
                prefer_coords_px=prefer_coords_px,
            )
            if hasattr(self.annotation_document, "_prefer_coords_px"):
                delattr(self.annotation_document, "_prefer_coords_px")

            if result.changed:
                logger.info(
                    "Annotation canonicalized for %s using %s strategy",
                    pdf_path,
                    result.strategy,
                )
        except Exception as e:
            logger.warning(f"Annotation canonicalization failed for {pdf_path}: {e}")

    def _update_has_annotation_flag(self, has_annotation: bool):
        """Обновить флаг has_annotation в узле дерева (через DocumentService)."""
        if not hasattr(self, "_current_node_id") or not self._current_node_id:
            return

        try:
            svc = get_document_service()
            result = svc.update_node_annotation_flag(
                self._current_node_id,
                has_annotation,
                r2_key=getattr(self, "_current_r2_key", None),
            )

            # Обновляем UI дерева если статус изменился
            if result and hasattr(self, "project_tree") and self.project_tree:
                status_value, message = result
                item = self.project_tree._node_map.get(self._current_node_id)
                if item:
                    node = item.data(0, Qt.UserRole)
                    if node:
                        node.pdf_status = status_value
                        node.pdf_status_message = message

                        from app.gui.tree_node_operations import NODE_ICONS

                        icon = NODE_ICONS.get(node.node_type, "📄")
                        status_icon = self.project_tree._get_pdf_status_icon(status_value)
                        lock_icon = "🔒" if node.is_locked else ""

                        display_name = f"{icon} {node.name} {lock_icon} {status_icon}".strip()
                        item.setText(0, display_name)
                        if message:
                            item.setToolTip(0, message)
        except Exception as e:
            logger.debug(f"Update has_annotation failed: {e}")

    def _load_annotation_if_exists(self, pdf_path: str, r2_key: str = ""):
        """Загрузить аннотацию через DocumentService (3-source fallback)."""
        from app.gui.toast import show_toast

        svc = get_document_service()
        result = svc.load_annotation(self._current_node_id, pdf_path, r2_key)

        if result.success and result.document:
            self.annotation_document = result.document
            self._canonicalize_loaded_annotation(pdf_path)

            # Инициализируем кеш аннотаций
            if self._current_node_id:
                from app.gui.annotation_cache import get_annotation_cache
                cache = get_annotation_cache()
                cache.set(self._current_node_id, self.annotation_document, pdf_path)

            self._annotation_synced = True
            self._update_has_annotation_flag(True)

            if result.message:
                show_toast(self, result.message, duration=3000, success=True)

            return True

        # Обработка ошибок миграции JSON (нужен GUI диалог)
        if not result.success and result.message and self._current_node_id:
            ann_path = Path(pdf_path).parent / f"{Path(pdf_path).stem}_annotation.json"
            if ann_path.exists():
                reply = QMessageBox.warning(
                    self,
                    "Ошибка аннотации",
                    f"{result.message}\n\nСоздать новый файл разметки?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    try:
                        ann_path.unlink()
                    except Exception:
                        pass
                    show_toast(self, "Создана новая разметка", success=True)

        return False

    def _create_empty_annotation(self, pdf_path: str) -> Document:
        """Создать пустой документ аннотации со страницами"""
        doc = Document(pdf_path=pdf_path)
        for page_num in range(self.pdf_document.page_count):
            if page_num in self.page_images:
                img = self.page_images[page_num]
                page = Page(page_number=page_num, width=img.width, height=img.height)
            else:
                dims = self.pdf_document.get_page_dimensions(page_num)
                if dims:
                    page = Page(page_number=page_num, width=dims[0], height=dims[1])
                else:
                    page = Page(page_number=page_num, width=595, height=842)
            doc.pages.append(page)
        return doc

    def _apply_ocr_from_local_result(self, pdf_path: str):
        """Применить ocr_text из локального _result.json (через DocumentService)."""
        if not self.annotation_document:
            return

        svc = get_document_service()
        updated = svc.apply_ocr_from_local_result(self.annotation_document, pdf_path)
        if updated > 0:
            self._auto_save_annotation()

    def _open_pdf(self):
        """Открыть PDF файл через диалог"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Открыть PDF", "", "PDF Files (*.pdf)"
        )
        if file_path:
            self._open_pdf_file(file_path)

    def _open_pdf_file(self, pdf_path: str, r2_key: str = ""):
        """Открыть PDF файл напрямую"""
        # Сохранить изменения предыдущего файла
        self._flush_pending_save()

        if self.pdf_document:
            self.pdf_document.close()

        self.page_images.clear()
        self._page_images_order.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()

        # Сброс флага синхронизации для нового файла
        self._annotation_synced = False

        self.pdf_document = PDFDocument(pdf_path)
        if not self.pdf_document.open() or self.pdf_document.page_count == 0:
            QMessageBox.warning(self, "Ошибка", "PDF файл пустой или повреждён")
            return

        self.current_page = 0
        self._current_pdf_path = pdf_path
        self._current_r2_key = r2_key

        # Переключить логи в папку PDF (но не в temp-папку для tree-документов)
        from app.logging_manager import get_logging_manager
        session = self._session_manager.current
        if not (session and session.is_tree_temp):
            get_logging_manager().switch_to_pdf_folder(pdf_path)

        # Пробуем загрузить существующую разметку
        if not self._load_annotation_if_exists(pdf_path, r2_key):
            # Создаём пустой документ аннотации
            self.annotation_document = self._create_empty_annotation(pdf_path)

        self._canonicalize_loaded_annotation(pdf_path)

        # Рендерим первую страницу
        self._render_current_page()
        self._update_ui()

        # Загружаем OCR result file для preview
        if hasattr(self, "_load_ocr_result_file"):
            self._load_ocr_result_file()

        # Применяем ocr_text из локального result.json (если блоки без ocr_text)
        self._apply_ocr_from_local_result(pdf_path)

        # Обновляем статистику OCR
        if hasattr(self, "remote_ocr_panel") and self.remote_ocr_panel:
            self.remote_ocr_panel.update_ocr_stats()

        # Обновляем заголовок
        self.setWindowTitle(f"{__product__} - {Path(pdf_path).name}")

    def _save_annotation(self):
        """Сохранить разметку в Supabase (или в JSON через диалог)."""
        if not self.annotation_document:
            return

        from app.gui.toast import show_toast

        # Если есть node_id — сохраняем через DocumentService
        if self._current_node_id:
            svc = get_document_service()
            success = svc.save_annotation(self.annotation_document, self._current_node_id)
            if success:
                show_toast(self, "Разметка сохранена в Supabase", success=True)
                self._update_has_annotation_flag(True)
            else:
                show_toast(self, "Ошибка сохранения в Supabase")
            return

        # Fallback: сохранение в JSON файл (для локального использования без дерева)
        default_path = ""
        if hasattr(self, "_current_pdf_path") and self._current_pdf_path:
            pdf_path = Path(self._current_pdf_path)
            default_path = str(pdf_path.parent / f"{pdf_path.stem}_annotation.json")

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить разметку", default_path, "JSON Files (*.json)"
        )
        if file_path:
            AnnotationIO.save_annotation(self.annotation_document, file_path)
            show_toast(self, "Разметка сохранена")

    def _load_annotation(self):
        """Загрузить разметку из JSON и мигрировать в Supabase"""
        from app.gui.toast import show_toast

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить разметку", "", "JSON Files (*.json)"
        )
        if not file_path:
            return

        loaded_doc, result = AnnotationIO.load_and_migrate(file_path)

        if not result.success:
            error_msg = "; ".join(result.errors)
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось загрузить разметку:\n{error_msg}"
            )
            return

        if loaded_doc:
            # Поддержка относительного пути
            try:
                pdf_path_obj = Path(loaded_doc.pdf_path)
                if not pdf_path_obj.is_absolute():
                    resolved = (Path(file_path).parent / pdf_path_obj).resolve()
                    loaded_doc.pdf_path = str(resolved)
            except Exception:
                pass

            self.annotation_document = loaded_doc
            pdf_path = loaded_doc.pdf_path
            if Path(pdf_path).exists():
                self._open_pdf_file(pdf_path)
                self.annotation_document = loaded_doc
                self._canonicalize_loaded_annotation(pdf_path)

                if self._current_node_id:
                    from app.gui.annotation_cache import get_annotation_cache

                    cache = get_annotation_cache()
                    cache.set(self._current_node_id, self.annotation_document, pdf_path)

                self._render_current_page()

            # Сохраняем в Supabase если есть node_id
            if self._current_node_id:
                svc = get_document_service()
                svc.save_annotation(loaded_doc, self._current_node_id)
                show_toast(self, "Разметка загружена и сохранена в Supabase", success=True)
            else:
                show_toast(self, "Разметка загружена", success=True)

            self.blocks_tree_manager.update_blocks_tree()

    def _on_annotation_replaced(self, r2_key: str):
        """Обработчик замены аннотации в дереве проектов (через DocumentService)."""
        from app.gui.toast import show_toast

        if not hasattr(self, "_current_r2_key") or self._current_r2_key != r2_key:
            return
        if not self._current_pdf_path or not self._current_node_id:
            return

        try:
            svc = get_document_service()
            loaded_doc = svc.reload_annotation_from_db(self._current_node_id)
            if not loaded_doc:
                logger.warning(f"Не удалось загрузить аннотацию: {self._current_node_id}")
                return

            self.annotation_document = loaded_doc
            self._canonicalize_loaded_annotation(self._current_pdf_path)
            self._annotation_synced = True

            from app.gui.annotation_cache import get_annotation_cache
            cache = get_annotation_cache()
            cache.set(self._current_node_id, self.annotation_document, self._current_pdf_path)

            self._render_current_page()
            if hasattr(self, "blocks_tree_manager") and self.blocks_tree_manager:
                self.blocks_tree_manager.update_blocks_tree()
            logger.info(f"Аннотация обновлена из Supabase: {self._current_node_id}")
            show_toast(self, "Аннотация обновлена", success=True)

        except Exception as e:
            logger.error(f"Ошибка обновления аннотации: {e}")
