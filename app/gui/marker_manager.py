"""
Менеджер Marker API для сегментации PDF
"""

import copy
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional, List
from PySide6.QtWidgets import QMessageBox

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class MarkerManager:
    """Управление Marker API сегментацией"""
    
    def __init__(self, parent: 'MainWindow'):
        self.parent = parent
    
    # === Paddle (PP-StructureV3) ===
    def segment_current_page_paddle(self):
        """Разметка текущей страницы через Paddle"""
        self._run_marker_worker(page_range=[self.parent.current_page], show_success=False, engine="paddle")
    
    def segment_all_pages_paddle(self):
        """Разметка всех страниц через Paddle"""
        self._run_marker_worker(page_range=None, show_success=True, engine="paddle")
    
    # === Surya ===
    def segment_current_page_surya(self):
        """Разметка текущей страницы через Surya"""
        self._run_marker_worker(page_range=[self.parent.current_page], show_success=False, engine="surya")
    
    def segment_all_pages_surya(self):
        """Разметка всех страниц через Surya"""
        self._run_marker_worker(page_range=None, show_success=True, engine="surya")
    
    # === Merged (Surya + Paddle) ===
    def segment_current_page_merged(self):
        """Разметка текущей страницы совмещением Surya + Paddle"""
        self._run_marker_worker(page_range=[self.parent.current_page], show_success=False, engine="merged")
    
    def segment_all_pages_merged(self):
        """Разметка всех страниц совмещением Surya + Paddle"""
        self._run_marker_worker(page_range=None, show_success=True, engine="merged")
    
    # === Устаревшие методы (совместимость) ===
    def segment_current_page(self):
        self.segment_current_page_paddle()
    
    def segment_all_pages(self):
        self.segment_all_pages_paddle()
    
    def _run_marker_worker(self, page_range: Optional[List[int]] = None, show_success: bool = True, engine: str = "paddle"):
        """Запуск API сегментации в фоновом режиме"""
        from app.gui.task_manager import TaskType
        
        if not self.parent.annotation_document or not self.parent.pdf_document:
            QMessageBox.warning(self.parent, "Внимание", "Сначала откройте PDF")
            return
        
        # Рендер страниц
        if page_range and len(page_range) == 1:
            page_num = page_range[0]
            if page_num not in self.parent.page_images:
                img = self.parent.pdf_document.render_page(page_num)
                if img:
                    self.parent.page_images[page_num] = img

        # Создаем задачу
        pdf_name = Path(self.parent.annotation_document.pdf_path).stem
        page_info = f"стр. {page_range[0]+1}" if page_range and len(page_range) == 1 else "все стр."
        engine_label = "Surya" if engine == "surya" else "Paddle"
        task_id = self.parent.task_manager.create_task(
            TaskType.MARKER,
            f"{engine_label}: {pdf_name} ({page_info})",
            self.parent.annotation_document.pdf_path
        )
        
        # Глубокая копия для thread-safety
        pages_copy = copy.deepcopy(self.parent.annotation_document.pages)
        page_images_copy = dict(self.parent.page_images)
        
        # Сохраняем контекст файла
        task_project_id = self.parent._current_project_id
        task_file_index = self.parent._current_file_index
        
        def on_completed(tid):
            if tid == task_id:
                task = self.parent.task_manager.get_task(tid)
                if task and task.result:
                    updated_pages = task.result
                    
                    is_same_file = (
                        self.parent._current_project_id == task_project_id and
                        self.parent._current_file_index == task_file_index
                    )
                    
                    if is_same_file:
                        self.parent.annotation_document.pages = updated_pages
                        
                        saved_transform = self.parent.page_viewer.transform()
                        saved_zoom = self.parent.page_viewer.zoom_factor
                        
                        self.parent._render_current_page()
                        self.parent.blocks_tree_manager.update_blocks_tree()
                        self.parent.category_manager.extract_categories_from_document()
                        
                        self.parent.page_viewer.setTransform(saved_transform)
                        self.parent.page_viewer.zoom_factor = saved_zoom
                    else:
                        cache_key = (task_project_id, task_file_index)
                        if cache_key in self.parent.annotations_cache:
                            self.parent.annotations_cache[cache_key].pages = updated_pages
                    
                    if show_success:
                        total_blocks = sum(len(p.blocks) for p in updated_pages)
                        QMessageBox.information(self.parent, "Успех", f"Сегментация завершена. Всего блоков: {total_blocks}")
                elif show_success:
                    QMessageBox.warning(self.parent, "Ошибка", "Не удалось обработать PDF")
        
        def on_failed(tid, error):
            if tid == task_id:
                QMessageBox.critical(self.parent, "Ошибка", f"Ошибка сегментации: {error}")
        
        self.parent.task_manager.task_completed.connect(on_completed)
        self.parent.task_manager.task_failed.connect(on_failed)
        
        self.parent.task_manager.start_marker_task(
            task_id,
            self.parent.pdf_document.pdf_path,
            pages_copy,
            page_images_copy,
            page_range,
            self.parent.active_category,
            engine
        )

