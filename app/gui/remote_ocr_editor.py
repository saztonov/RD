"""Mixin для открытия результатов Remote OCR в редакторе"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EditorMixin:
    """Миксин для открытия результатов задач в редакторе"""
    
    def _open_job_in_editor(self, job_id: str):
        """Открыть результат задачи в редакторе"""
        if job_id in self._job_output_dirs:
            extract_dir = Path(self._job_output_dirs[job_id])
        else:
            from app.gui.folder_settings_dialog import get_download_jobs_dir
            download_dir = get_download_jobs_dir()
            if download_dir and Path(download_dir).exists():
                extract_dir = Path(download_dir) / f"result_{job_id[:8]}"
            else:
                import tempfile
                tmp_base = Path(tempfile.gettempdir()) / "rd_ocr_results"
                tmp_base.mkdir(exist_ok=True)
                extract_dir = tmp_base / f"result_{job_id[:8]}"
            self._job_output_dirs[job_id] = str(extract_dir)
            self._save_job_mappings()

        annotation_path = extract_dir / "annotation.json"
        pdf_path = extract_dir / "document.pdf"

        if not annotation_path.exists() or not pdf_path.exists():
            self._auto_download_result(job_id, open_after=True)
            return
        
        self._open_job_in_editor_internal(job_id)

    def _open_job_in_editor_internal(self, job_id: str):
        """Внутренний метод открытия задачи"""
        try:
            extract_dir = Path(self._job_output_dirs[job_id])
            annotation_path = extract_dir / "annotation.json"
            pdf_path = extract_dir / "document.pdf"

            if not annotation_path.exists():
                QMessageBox.warning(self, "Нет результата", "annotation.json не найден")
                return

            from rd_core.annotation_io import AnnotationIO
            loaded_doc = AnnotationIO.load_annotation(str(annotation_path))
            if not loaded_doc:
                QMessageBox.critical(self, "Ошибка", "Не удалось загрузить annotation.json")
                return

            if pdf_path.exists():
                loaded_doc.pdf_path = str(pdf_path)
            else:
                try:
                    pdf_path_obj = Path(loaded_doc.pdf_path)
                    if not pdf_path_obj.is_absolute():
                        loaded_doc.pdf_path = str((annotation_path.parent / pdf_path_obj).resolve())
                except Exception:
                    pass

            pdf_abs_path = Path(loaded_doc.pdf_path)
            if not pdf_abs_path.exists():
                QMessageBox.warning(self, "PDF не найден", f"PDF файл не найден:\n{loaded_doc.pdf_path}")
                return

            try:
                from rd_core.models import Page
                from rd_core.pdf_utils import PDFDocument

                blocks_by_page: dict[int, list] = {}
                page_dims: dict[int, tuple[int, int]] = {}

                for p in loaded_doc.pages:
                    if getattr(p, "width", 0) and getattr(p, "height", 0):
                        page_dims[p.page_number] = (int(p.width), int(p.height))
                    for b in (p.blocks or []):
                        blocks_by_page.setdefault(int(getattr(b, "page_index", p.page_number)), []).append(b)

                with PDFDocument(str(pdf_abs_path)) as pdf:
                    new_pages = []
                    for page_idx in range(pdf.page_count):
                        dims = page_dims.get(page_idx) or pdf.get_page_dimensions(page_idx) or (595, 842)
                        blocks = blocks_by_page.get(page_idx, [])
                        try:
                            blocks.sort(key=lambda bl: bl.coords_px[1])
                        except Exception:
                            pass
                        new_pages.append(Page(page_number=page_idx, width=int(dims[0]), height=int(dims[1]), blocks=blocks))
                loaded_doc.pages = new_pages
            except Exception:
                pass

            try:
                crops_dir = annotation_path.parent / "crops"
                if crops_dir.exists():
                    for page in loaded_doc.pages:
                        for block in page.blocks:
                            if not getattr(block, "image_file", None):
                                continue
                            fname = Path(block.image_file).name
                            local_img = crops_dir / fname
                            block.image_file = str(local_img.resolve()) if local_img.exists() else str(local_img)
            except Exception:
                pass

            self.main_window._open_pdf_file(str(pdf_abs_path))
            self.main_window.annotation_document = loaded_doc
            self.main_window._current_pdf_path = str(pdf_abs_path)

            if hasattr(self.main_window, "page_viewer") and self.main_window.page_viewer:
                try:
                    self.main_window.page_viewer.selected_block_idx = None
                    self.main_window.page_viewer.selected_block_indices = []
                except Exception:
                    pass

            self.main_window._render_current_page()

            if getattr(self.main_window, "blocks_tree_manager", None):
                self.main_window.blocks_tree_manager.update_blocks_tree()

        except Exception as e:
            logger.error(f"Ошибка открытия задачи {job_id}: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть задачу:\n{e}")
    
    def _show_job_details(self, job_id: str):
        """Показать детальную информацию о задаче"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            job_details = client.get_job_details(job_id)
            
            if job_id not in self._job_output_dirs:
                from app.gui.folder_settings_dialog import get_download_jobs_dir
                download_dir = get_download_jobs_dir()
                if download_dir and Path(download_dir).exists():
                    extract_dir = Path(download_dir) / f"result_{job_id[:8]}"
                else:
                    import tempfile
                    extract_dir = Path(tempfile.gettempdir()) / "rd_ocr_results" / f"result_{job_id[:8]}"
                
                self._job_output_dirs[job_id] = str(extract_dir)
                self._save_job_mappings()
            
            extract_dir = Path(self._job_output_dirs[job_id])
            if job_details.get("status") == "done" and not (extract_dir / "annotation.json").exists():
                self._auto_download_result(job_id)
            
            job_details["client_output_dir"] = self._job_output_dirs[job_id]
            
            from app.gui.job_details_dialog import JobDetailsDialog
            dialog = JobDetailsDialog(job_details, self)
            dialog.exec()
        except Exception as e:
            logger.error(f"Ошибка получения информации о задаче: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить информацию:\n{e}")

