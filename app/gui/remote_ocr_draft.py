"""Mixin для работы с черновиками Remote OCR"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DraftMixin:
    """Миксин для создания и управления черновиками задач"""
    
    def _save_draft(self):
        """Сохранить черновик на сервере"""
        if not self.main_window.pdf_document or not self.main_window.annotation_document:
            QMessageBox.warning(self, "Ошибка", "Откройте PDF документ")
            return
        
        pdf_path = self.main_window.annotation_document.pdf_path
        if not pdf_path or not Path(pdf_path).exists():
            if hasattr(self.main_window, '_current_pdf_path') and self.main_window._current_pdf_path:
                pdf_path = self.main_window._current_pdf_path
                self.main_window.annotation_document.pdf_path = pdf_path
        
        if not pdf_path or not Path(pdf_path).exists():
            QMessageBox.warning(self, "Ошибка", "PDF файл не найден")
            return
        
        total_blocks = sum(len(p.blocks) for p in self.main_window.annotation_document.pages)
        if total_blocks == 0:
            QMessageBox.warning(self, "Ошибка", "Нет блоков для сохранения")
            return
        
        client = self._get_client()
        if client is None:
            QMessageBox.warning(self, "Ошибка", "Клиент не инициализирован")
            return
        
        task_name = Path(pdf_path).stem if pdf_path else ""
        
        from app.gui.folder_settings_dialog import get_new_jobs_dir
        from app.gui.ocr_dialog import transliterate_to_latin
        
        base_dir = get_new_jobs_dir()
        if base_dir:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_task_name = transliterate_to_latin(task_name) if task_name else "draft"
            unique_name = f"{safe_task_name}_{timestamp}"
            self._pending_output_dir = str(Path(base_dir) / unique_name)
        else:
            import tempfile
            self._pending_output_dir = str(Path(tempfile.gettempdir()) / "rd_draft")
        
        from app.gui.toast import show_toast
        show_toast(self, "Сохранение черновика...", duration=1500)
        
        self._executor.submit(self._save_draft_bg, client, pdf_path, self.main_window.annotation_document, task_name)
    
    def _save_draft_bg(self, client, pdf_path, annotation_document, task_name):
        """Фоновое сохранение черновика"""
        try:
            from app.remote_ocr_client import AuthenticationError, PayloadTooLargeError, ServerError
            
            job_info = client.create_draft(pdf_path, annotation_document, task_name=task_name)
            self._signals.draft_created.emit(job_info)
        except AuthenticationError:
            self._signals.draft_create_error.emit("auth", "Неверный API ключ.")
        except PayloadTooLargeError:
            self._signals.draft_create_error.emit("size", "PDF файл превышает лимит сервера.")
        except ServerError as e:
            self._signals.draft_create_error.emit("server", f"Сервер недоступен.\n{e}")
        except Exception as e:
            self._signals.draft_create_error.emit("generic", str(e))
    
    def _on_draft_created(self, job_info):
        """Слот: черновик создан"""
        self._job_output_dirs[job_info.id] = self._pending_output_dir
        self._save_job_mappings()
        
        try:
            output_dir = Path(self._pending_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            import shutil
            pdf_path = self.main_window.annotation_document.pdf_path
            shutil.copy2(pdf_path, output_dir / "document.pdf")
            
            from rd_core.annotation_io import AnnotationIO
            AnnotationIO.save_annotation(self.main_window.annotation_document, str(output_dir / "annotation.json"))
        except Exception as e:
            logger.warning(f"Ошибка локального сохранения черновика: {e}")
        
        from app.gui.toast import show_toast
        show_toast(self, f"Черновик сохранён: {job_info.id[:8]}...", duration=2500)
        self._refresh_jobs(manual=True)
    
    def _on_draft_create_error(self, error_type: str, message: str):
        """Слот: ошибка создания черновика"""
        titles = {"auth": "Ошибка авторизации", "size": "Файл слишком большой", "server": "Ошибка сервера", "generic": "Ошибка"}
        QMessageBox.critical(self, titles.get(error_type, "Ошибка"), message)

