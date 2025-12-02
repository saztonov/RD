"""
Менеджер фоновых заданий
"""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QThread
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Статус задания"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class TaskType(Enum):
    """Тип задания"""
    OCR = "ocr"
    MARKER = "marker"


@dataclass
class Task:
    """Задание для обработки"""
    id: str
    task_type: TaskType
    name: str
    pdf_path: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    max_progress: int = 100
    error_message: Optional[str] = None
    created_at: datetime = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class OCRWorker(QThread):
    """Фоновый поток для OCR"""
    progress = Signal(int, int)  # current, total
    finished = Signal(object)  # result
    error = Signal(str)
    
    def __init__(self, task_id, annotation_document, pdf_document, page_images, config):
        super().__init__()
        self.task_id = task_id
        self.annotation_document = annotation_document
        self.pdf_document = pdf_document
        self.page_images = page_images
        self.config = config
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        try:
            from app.ocr import create_ocr_engine, generate_structured_markdown, load_prompt
            from app.annotation_io import AnnotationIO
            from app.models import BlockType
            
            output_dir = Path(self.config['output_dir'])
            crops_dir = output_dir / "crops"
            crops_dir.mkdir(parents=True, exist_ok=True)
            
            # OCR Engine
            if self.config['backend'] == 'openrouter':
                import os
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.getenv("OPENROUTER_API_KEY")
                
                text_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=self.config.get('text_model'))
                table_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=self.config.get('table_model'))
                image_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=self.config.get('image_model'))
            else:
                api_base = self.config['vlm_server_url']
                model_name = self.config['vlm_model_name']
                text_engine = table_engine = image_engine = create_ocr_engine("local_vlm", api_base=api_base, model_name=model_name)
            
            total_blocks = sum(len(p.blocks) for p in self.annotation_document.pages)
            processed_count = 0
            
            for page in self.annotation_document.pages:
                if self._cancelled:
                    break
                
                page_num = page.page_number
                if page_num not in self.page_images:
                    img = self.pdf_document.render_page(page_num)
                    if img:
                        self.page_images[page_num] = img
                
                page_img = self.page_images.get(page_num)
                if not page_img:
                    continue
                
                for block in page.blocks:
                    if self._cancelled:
                        break
                    
                    x1, y1, x2, y2 = block.coords_px
                    if x1 >= x2 or y1 >= y2:
                        processed_count += 1
                        self.progress.emit(processed_count, total_blocks)
                        continue
                    
                    crop = page_img.crop((x1, y1, x2, y2))
                    
                    try:
                        if block.block_type == BlockType.IMAGE:
                            crop_filename = f"page{page_num}_block{block.id}.png"
                            crop_path = crops_dir / crop_filename
                            crop.save(crop_path, "PNG")
                            block.image_file = str(crop_path)
                        
                        if block.block_type == BlockType.IMAGE:
                            image_prompt = load_prompt("ocr_image_description.txt")
                            block.ocr_text = image_engine.recognize(crop, prompt=image_prompt)
                        elif block.block_type == BlockType.TABLE:
                            table_prompt = load_prompt("ocr_table.txt")
                            block.ocr_text = table_engine.recognize(crop, prompt=table_prompt) if table_prompt else table_engine.recognize(crop)
                        elif block.block_type == BlockType.TEXT:
                            text_prompt = load_prompt("ocr_text.txt")
                            block.ocr_text = text_engine.recognize(crop, prompt=text_prompt) if text_prompt else text_engine.recognize(crop)
                    except Exception as e:
                        logger.error(f"Error OCR block {block.id}: {e}")
                        block.ocr_text = f"[Error: {e}]"
                    
                    processed_count += 1
                    self.progress.emit(processed_count, total_blocks)
            
            if not self._cancelled:
                # Сохранение результатов
                json_path = output_dir / "annotation.json"
                AnnotationIO.save_annotation(self.annotation_document, str(json_path))
                
                md_path = output_dir / "document.md"
                generate_structured_markdown(self.annotation_document.pages, str(md_path))
                
                # Загрузка в R2
                try:
                    from app.r2_storage import upload_ocr_to_r2
                    project_name = output_dir.name
                    logger.info(f"OCRWorker: Загрузка результатов в R2 (проект: {project_name})")
                    upload_ocr_to_r2(str(output_dir), project_name)
                except Exception as e:
                    logger.error(f"OCRWorker: Ошибка загрузки в R2: {e}", exc_info=True)
                
                self.finished.emit({'output_dir': str(output_dir), 'updated_pages': self.annotation_document.pages})
            
        except Exception as e:
            logger.error(f"OCR Worker error: {e}", exc_info=True)
            self.error.emit(str(e))


class MarkerWorker(QThread):
    """Фоновый поток для Marker"""
    progress = Signal(int, int)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, task_id, pdf_path, pages, page_images, page_range, category):
        super().__init__()
        self.task_id = task_id
        self.pdf_path = pdf_path
        self.pages = pages
        self.page_images = page_images
        self.page_range = page_range
        self.category = category
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        try:
            if self._cancelled:
                return
            
            from app.marker_integration import segment_with_marker
            result = segment_with_marker(self.pdf_path, self.pages, self.page_images, self.page_range, self.category)
            
            if not self._cancelled:
                self.finished.emit(result)
        except Exception as e:
            logger.error(f"Marker Worker error: {e}", exc_info=True)
            self.error.emit(str(e))


class TaskManager(QObject):
    """Менеджер фоновых заданий"""
    
    task_added = Signal(str)  # task_id
    task_updated = Signal(str)  # task_id
    task_completed = Signal(str)  # task_id
    task_failed = Signal(str, str)  # task_id, error_message
    
    def __init__(self):
        super().__init__()
        self.tasks: Dict[str, Task] = {}
        self.workers: Dict[str, QThread] = {}
        self._task_counter = 0
    
    def create_task(self, task_type: TaskType, name: str, pdf_path: str) -> str:
        """Создать новое задание"""
        self._task_counter += 1
        task_id = f"{task_type.value}_{self._task_counter}_{datetime.now().strftime('%H%M%S')}"
        
        task = Task(
            id=task_id,
            task_type=task_type,
            name=name,
            pdf_path=pdf_path
        )
        
        self.tasks[task_id] = task
        self.task_added.emit(task_id)
        return task_id
    
    def start_ocr_task(self, task_id: str, annotation_document, pdf_document, page_images, config):
        """Запустить OCR задание"""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.status = TaskStatus.RUNNING
        task.max_progress = sum(len(p.blocks) for p in annotation_document.pages)
        self.task_updated.emit(task_id)
        
        worker = OCRWorker(task_id, annotation_document, pdf_document, page_images, config)
        worker.progress.connect(lambda current, total: self._on_progress(task_id, current, total))
        worker.finished.connect(lambda result: self._on_task_finished(task_id, result))
        worker.error.connect(lambda error: self._on_task_error(task_id, error))
        
        self.workers[task_id] = worker
        worker.start()
    
    def start_marker_task(self, task_id: str, pdf_path, pages, page_images, page_range, category):
        """Запустить Marker задание"""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.status = TaskStatus.RUNNING
        self.task_updated.emit(task_id)
        
        worker = MarkerWorker(task_id, pdf_path, pages, page_images, page_range, category)
        worker.finished.connect(lambda result: self._on_task_finished(task_id, result))
        worker.error.connect(lambda error: self._on_task_error(task_id, error))
        
        self.workers[task_id] = worker
        worker.start()
    
    def cancel_task(self, task_id: str):
        """Отменить задание"""
        if task_id in self.workers:
            worker = self.workers[task_id]
            if hasattr(worker, 'cancel'):
                worker.cancel()
            worker.quit()
            worker.wait()
            del self.workers[task_id]
        
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.CANCELLED
            self.task_updated.emit(task_id)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Получить задание по ID"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self):
        """Получить все задания"""
        return list(self.tasks.values())
    
    def _on_progress(self, task_id: str, current: int, total: int):
        """Обработка прогресса задания"""
        if task_id in self.tasks:
            self.tasks[task_id].progress = current
            self.tasks[task_id].max_progress = total
            self.task_updated.emit(task_id)
    
    def _on_task_finished(self, task_id: str, result):
        """Обработка завершения задания"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.SUCCESS
            self.tasks[task_id].completed_at = datetime.now()
            self.tasks[task_id].result = result
            self.task_completed.emit(task_id)
            self.task_updated.emit(task_id)
        
        if task_id in self.workers:
            del self.workers[task_id]
    
    def _on_task_error(self, task_id: str, error_message: str):
        """Обработка ошибки задания"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.ERROR
            self.tasks[task_id].error_message = error_message
            self.tasks[task_id].completed_at = datetime.now()
            self.task_failed.emit(task_id, error_message)
            self.task_updated.emit(task_id)
        
        if task_id in self.workers:
            del self.workers[task_id]

