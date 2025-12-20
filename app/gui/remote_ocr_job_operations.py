"""Mixin для операций с Remote OCR задачами (CRUD, pause/resume)"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class JobOperationsMixin:
    """Миксин для операций с задачами: создание, удаление, пауза, возобновление, перезапуск"""
    
    def _create_job(self):
        """Создать новую задачу OCR"""
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
        
        from PySide6.QtWidgets import QDialog
        from app.gui.ocr_dialog import OCRDialog
        
        task_name = Path(pdf_path).stem if pdf_path else ""
        
        dialog = OCRDialog(self.main_window, task_name=task_name)
        if dialog.exec() != QDialog.Accepted:
            return
        
        self._last_output_dir = dialog.output_dir
        self._last_engine = dialog.ocr_backend
        
        selected_blocks = self._get_selected_blocks()
        if not selected_blocks:
            QMessageBox.warning(self, "Ошибка", "Нет блоков для распознавания")
            return
        
        client = self._get_client()
        if client is None:
            QMessageBox.warning(self, "Ошибка", "Клиент не инициализирован")
            return
        
        engine = "openrouter"
        if dialog.ocr_backend == "datalab":
            engine = "datalab"
        elif dialog.ocr_backend == "openrouter":
            engine = "openrouter"
        
        self._pending_output_dir = dialog.output_dir
        
        from app.gui.toast import show_toast
        show_toast(self, "Отправка задачи...", duration=1500)
        
        self._executor.submit(
            self._create_job_bg, client, pdf_path, selected_blocks, task_name, engine,
            getattr(dialog, "text_model", None),
            getattr(dialog, "table_model", None),
            getattr(dialog, "image_model", None),
        )
        logger.info(f"OCR задача: image_model={getattr(dialog, 'image_model', None)}")
    
    def _create_job_bg(self, client, pdf_path, blocks, task_name, engine, text_model, table_model, image_model):
        """Фоновое создание задачи"""
        try:
            from app.remote_ocr_client import AuthenticationError, PayloadTooLargeError, ServerError
            
            job_info = client.create_job(pdf_path, blocks, task_name=task_name, engine=engine,
                                        text_model=text_model, table_model=table_model, image_model=image_model)
            self._signals.job_created.emit(job_info)
        except AuthenticationError:
            self._signals.job_create_error.emit("auth", "Неверный API ключ.")
        except PayloadTooLargeError:
            self._signals.job_create_error.emit("size", "PDF файл превышает лимит сервера.")
        except ServerError as e:
            self._signals.job_create_error.emit("server", f"Сервер недоступен.\n{e}")
        except Exception as e:
            self._signals.job_create_error.emit("generic", str(e))
    
    def _delete_job(self, job_id: str):
        """Удалить задачу и все связанные файлы"""
        reply = QMessageBox.question(self, "Подтверждение удаления",
            f"Удалить задачу {job_id[:8]}...?\n\nБудут удалены:\n• Запись на сервере\n• Файлы в R2\n• Локальная папка",
            QMessageBox.Yes | QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return
        
        client = self._get_client()
        if client is None:
            return
        
        try:
            client.delete_job(job_id)
            
            if job_id in self._job_output_dirs:
                local_dir = Path(self._job_output_dirs[job_id])
                if local_dir.exists():
                    import shutil
                    try:
                        shutil.rmtree(local_dir)
                    except Exception as e:
                        logger.warning(f"Ошибка удаления локальной папки: {e}")
                
                del self._job_output_dirs[job_id]
                self._save_job_mappings()
            
            from app.gui.toast import show_toast
            show_toast(self, "Задача удалена")
            self._refresh_jobs(manual=True)
            
        except Exception as e:
            logger.error(f"Ошибка удаления задачи: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить задачу:\n{e}")
    
    def _pause_job(self, job_id: str):
        """Поставить задачу на паузу"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            if client.pause_job(job_id):
                from app.gui.toast import show_toast
                show_toast(self, f"Задача {job_id[:8]}... на паузе")
                self._refresh_jobs(manual=True)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось поставить на паузу")
        except Exception as e:
            logger.error(f"Ошибка паузы задачи: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось поставить на паузу:\n{e}")
    
    def _resume_job(self, job_id: str):
        """Возобновить задачу с паузы"""
        client = self._get_client()
        if client is None:
            return
        
        try:
            if client.resume_job(job_id):
                from app.gui.toast import show_toast
                show_toast(self, f"Задача {job_id[:8]}... возобновлена")
                self._refresh_jobs(manual=True)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось возобновить")
        except Exception as e:
            logger.error(f"Ошибка возобновления задачи: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось возобновить:\n{e}")
    
    def _rerun_job(self, job_id: str):
        """Повторное распознавание с сохранёнными настройками"""
        reply = QMessageBox.question(
            self, "Повторное распознавание",
            f"Повторить распознавание задачи {job_id[:8]}?\n\nВсе результаты будут удалены и созданы заново.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        
        from app.gui.toast import show_toast
        show_toast(self, "Подготовка повторного распознавания...", duration=1500)
        
        self._executor.submit(self._rerun_job_bg, job_id)
    
    def _rerun_job_bg(self, job_id: str):
        """Фоновая повторная отправка на распознавание"""
        try:
            from app.remote_ocr_client import AuthenticationError, ServerError
            
            client = self._get_client()
            if client is None:
                self._signals.rerun_error.emit(job_id, "Клиент не инициализирован")
                return
            
            if job_id in self._job_output_dirs:
                local_dir = Path(self._job_output_dirs[job_id])
                if local_dir.exists():
                    import shutil
                    for fname in ["annotation.json", "result.md"]:
                        fpath = local_dir / fname
                        if fpath.exists():
                            try:
                                fpath.unlink()
                            except Exception:
                                pass
                    crops_dir = local_dir / "crops"
                    if crops_dir.exists():
                        try:
                            shutil.rmtree(crops_dir)
                        except Exception:
                            pass
            
            if not client.restart_job(job_id):
                self._signals.rerun_error.emit(job_id, "Не удалось перезапустить задачу")
                return
            
            self._signals.rerun_created.emit(job_id, None)
            
        except AuthenticationError:
            self._signals.rerun_error.emit(job_id, "Неверный API ключ")
        except ServerError as e:
            self._signals.rerun_error.emit(job_id, f"Сервер недоступен: {e}")
        except Exception as e:
            logger.error(f"Ошибка повторного распознавания: {e}")
            self._signals.rerun_error.emit(job_id, str(e))

