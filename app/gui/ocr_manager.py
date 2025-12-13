"""
OCR Manager для MainWindow
Управление OCR операциями и диалогами
"""

import logging
import copy
import os
from pathlib import Path
from PySide6.QtWidgets import QProgressDialog, QMessageBox, QDialog
from PySide6.QtCore import Qt
from dotenv import load_dotenv
from app.ocr import generate_structured_markdown
from app.annotation_io import AnnotationIO
from app.models import BlockType
from app.gui.task_manager import TaskManager, TaskType
from app.r2_storage import upload_ocr_to_r2

load_dotenv()
logger = logging.getLogger(__name__)


class OCRManager:
    """Управление OCR операциями"""
    
    def __init__(self, parent, task_manager: TaskManager = None):
        self.parent = parent
        self.task_manager = task_manager
    
    def _upload_to_r2(self, output_dir: Path):
        """Загрузить результаты в R2 Storage"""
        logger.info("=" * 60)
        logger.info("=== OCRManager: Вызов метода _upload_to_r2 ===")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Output directory exists: {output_dir.exists()}")
        
        try:
            project_name = output_dir.name
            logger.info(f"Project name: {project_name}")
            logger.info(f"Вызов upload_ocr_to_r2('{output_dir}', '{project_name}')")
            
            result = upload_ocr_to_r2(str(output_dir), project_name)
            
            if result:
                logger.info("✅ Результаты успешно загружены в R2")
            else:
                logger.warning("⚠️ Не удалось загрузить результаты в R2 (проверьте .env и логи выше)")
                
        except ValueError as e:
            logger.error(f"❌ Ошибка инициализации R2 (проверьте .env файл): {e}")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка загрузки в R2: {type(e).__name__}: {e}", exc_info=True)
    
    def run_ocr_all(self):
        """Запустить OCR для всех блоков через удалённый сервер"""
        if not self.parent.annotation_document or not self.parent.pdf_document:
            QMessageBox.warning(self.parent, "Внимание", "Сначала откройте PDF")
            return
        
        # Получаем имя задачи из активного проекта
        task_name = ""
        active_project = self.parent.project_manager.get_active_project()
        if active_project:
            task_name = active_project.name
        
        from app.gui.ocr_dialog import OCRDialog
        
        dialog = OCRDialog(self.parent, task_name=task_name)
        if dialog.exec() != QDialog.Accepted:
            return
        
        output_dir = Path(dialog.output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        crops_dir = output_dir / "crops"
        crops_dir.mkdir(exist_ok=True)
        
        import shutil
        pdf_name = Path(self.parent.annotation_document.pdf_path).name
        pdf_output = output_dir / pdf_name
        shutil.copy2(self.parent.annotation_document.pdf_path, pdf_output)
        logger.info(f"PDF сохранен: {pdf_output}")
        
        # Используем TaskManager для фонового выполнения через удалённый сервер
        if self.task_manager:
            self._run_ocr_background(output_dir, crops_dir, dialog)
        else:
            QMessageBox.critical(self.parent, "Ошибка", "TaskManager не инициализирован")
    
    def _run_ocr_background(self, output_dir: Path, crops_dir: Path, dialog):
        """Запуск OCR в фоновом режиме через TaskManager"""
        pdf_name = Path(self.parent.annotation_document.pdf_path).stem
        task_id = self.task_manager.create_task(
            TaskType.OCR,
            f"OCR: {pdf_name}",
            self.parent.annotation_document.pdf_path
        )
        
        # Подготовка конфига с загрузчиком промптов из R2
        config = {
            'output_dir': str(output_dir),
            'crops_dir': str(crops_dir),
            'backend': dialog.ocr_backend,
            'vlm_server_url': dialog.vlm_server_url,
            'vlm_model_name': dialog.vlm_model_name,
            'text_model': dialog.text_model,
            'table_model': dialog.table_model,
            'image_model': dialog.image_model,
            'prompt_loader': self.parent.prompt_manager.load_prompt if hasattr(self.parent, 'prompt_manager') else None,
            'use_batch_ocr': getattr(dialog, 'use_batch_ocr', True),
            # Datalab настройки
            'use_datalab': getattr(dialog, 'use_datalab', False),
            'datalab_image_backend': getattr(dialog, 'datalab_image_backend', 'local'),
            'datalab_api_key': os.getenv('DATALAB_API_KEY', ''),
        }
        
        # Глубокая копия документа для потока
        annotation_copy = copy.deepcopy(self.parent.annotation_document)
        page_images_copy = dict(self.parent.page_images)
        
        # Сохраняем контекст файла при запуске задачи
        task_project_id = self.parent._current_project_id
        task_file_index = self.parent._current_file_index
        task_pdf_path = self.parent.annotation_document.pdf_path
        
        # Подключаем обработчик завершения
        def on_completed(tid):
            if tid == task_id:
                task = self.task_manager.get_task(tid)
                if task and task.result:
                    result = task.result
                    if 'updated_pages' not in result:
                        return
                    
                    updated_pages = result['updated_pages']
                    
                    # Проверяем, тот ли файл сейчас активен
                    is_same_file = (
                        self.parent._current_project_id == task_project_id and
                        self.parent._current_file_index == task_file_index
                    )
                    
                    if is_same_file:
                        # Обновляем текущий документ
                        self.parent.annotation_document.pages = updated_pages
                        self.parent._render_current_page()
                        self.parent.blocks_tree_manager.update_blocks_tree()
                    else:
                        # Обновляем в кеше, если есть
                        cache_key = (task_project_id, task_file_index)
                        if cache_key in self.parent.annotations_cache:
                            self.parent.annotations_cache[cache_key].pages = updated_pages
                    
                    QMessageBox.information(
                        self.parent, 
                        "Готово", 
                        f"OCR завершен!\n\nРезультаты: {result.get('output_dir', output_dir)}"
                    )
        
        def on_failed(tid, error):
            if tid == task_id:
                QMessageBox.critical(self.parent, "Ошибка OCR", f"Ошибка:\n{error}")
        
        self.task_manager.task_completed.connect(on_completed)
        self.task_manager.task_failed.connect(on_failed)
        
        # Запуск
        self.task_manager.start_ocr_task(
            task_id,
            annotation_copy,
            self.parent.pdf_document,
            page_images_copy,
            config
        )
    
    
    def _get_prompt_for_block(self, block):
        """Получить промт для блока из R2 (приоритет: категория -> тип блока)"""
        # Приоритет 1: Промпт категории
        if block.category and block.category.strip():
            category_prompt = self.parent.prompt_manager.load_prompt(f"category_{block.category.strip()}")
            if category_prompt:
                return category_prompt
        
        # Приоритет 2: Промпт типа блока
        prompt_map = {
            BlockType.IMAGE: "image",
            BlockType.TABLE: "table",
            BlockType.TEXT: "text",
        }
        key = prompt_map.get(block.block_type, "text")
        return self.parent.prompt_manager.load_prompt(key)
    
    def _save_ocr_results(self, output_dir: Path):
        """Сохранить результаты OCR"""
        json_path = output_dir / "annotation.json"
        AnnotationIO.save_annotation(self.parent.annotation_document, str(json_path))
        logger.info(f"Разметка сохранена: {json_path}")
        
        md_path = output_dir / "document.md"
        project_name = output_dir.name
        generate_structured_markdown(self.parent.annotation_document.pages, str(md_path), project_name=project_name)
        logger.info(f"Markdown сохранен: {md_path}")
        
        self._upload_to_r2(output_dir)
        
        pdf_name = Path(self.parent.annotation_document.pdf_path).name
        QMessageBox.information(
            self.parent, 
            "Готово", 
            f"OCR завершен!\n\nРезультаты сохранены в:\n{output_dir}\n\n• {pdf_name}\n• annotation.json\n• crops/\n• document.md"
        )
    

