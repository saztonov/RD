"""
Главное окно приложения
Интеграция компонентов через миксины
"""

from typing import Optional
from PySide6.QtWidgets import QMainWindow
from app.models import Document, BlockType
from app.pdf_utils import PDFDocument
from app.gui.ocr_manager import OCRManager
from app.gui.blocks_tree_manager import BlocksTreeManager
from app.gui.category_manager import CategoryManager
from app.gui.prompt_manager import PromptManager
from app.gui.project_manager import ProjectManager
from app.gui.task_manager import TaskManager
from app.gui.navigation_manager import NavigationManager
from app.gui.marker_manager import MarkerManager
from app.gui.menu_setup import MenuSetupMixin
from app.gui.panels_setup import PanelsSetupMixin
from app.gui.file_operations import FileOperationsMixin
from app.gui.block_handlers import BlockHandlersMixin
from app.ocr import create_ocr_engine


class MainWindow(MenuSetupMixin, PanelsSetupMixin, FileOperationsMixin, 
                 BlockHandlersMixin, QMainWindow):
    """Главное окно приложения для аннотирования PDF"""
    
    def __init__(self):
        super().__init__()
        
        # Данные приложения
        self.pdf_document: Optional[PDFDocument] = None
        self.annotation_document: Optional[Document] = None
        self.current_page: int = 0
        self.page_images: dict = {}
        self.categories: list = []
        self.active_category: str = ""
        self.page_zoom_states: dict = {}
        self.annotations_cache: dict = {}
        self._current_project_id: Optional[str] = None
        self._current_file_index: int = -1
        
        # Компоненты
        self.ocr_engine = create_ocr_engine("dummy")
        
        # Менеджеры (инициализируются после setup_ui)
        self.project_manager = ProjectManager()
        self.task_manager = TaskManager()
        self.prompt_manager = PromptManager(self)
        self.ocr_manager = None
        self.blocks_tree_manager = None
        self.category_manager = None
        self.project_sidebar = None
        self.task_sidebar = None
        self.navigation_manager = None
        self.marker_manager = None
        
        # Настройка UI
        self._setup_menu()
        self._setup_toolbar()
        self._setup_ui()
        
        # Инициализация менеджеров после создания UI
        self.ocr_manager = OCRManager(self, self.task_manager)
        self.blocks_tree_manager = BlocksTreeManager(self, self.blocks_tree, self.blocks_tree_by_category)
        self.category_manager = CategoryManager(self, self.categories_list)
        self.navigation_manager = NavigationManager(self)
        self.marker_manager = MarkerManager(self)
        
        self.prompt_manager.ensure_default_prompts()
        
        self.setWindowTitle("PDF Annotation Tool")
        self.resize(1200, 800)
    
    def _render_current_page(self, update_tree: bool = True):
        """Отрендерить текущую страницу"""
        if not self.pdf_document:
            return
        
        self.navigation_manager.load_page_image(self.current_page)
        
        if self.current_page in self.page_images:
            self.navigation_manager.restore_zoom()
            
            current_page_data = self._get_or_create_page(self.current_page)
            self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
            
            if update_tree:
                self.blocks_tree_manager.update_blocks_tree()
    
    def _update_ui(self):
        """Обновить UI элементы"""
        if self.pdf_document:
            self.page_label.setText(f"Страница: {self.current_page + 1} / {self.pdf_document.page_count}")
        else:
            self.page_label.setText("Страница: 0 / 0")
    
    def _prev_page(self):
        """Предыдущая страница"""
        self.navigation_manager.prev_page()
    
    def _next_page(self):
        """Следующая страница"""
        self.navigation_manager.next_page()
    
    def _zoom_in(self):
        """Увеличить масштаб"""
        self.navigation_manager.zoom_in()
    
    def _zoom_out(self):
        """Уменьшить масштаб"""
        self.navigation_manager.zoom_out()
    
    def _zoom_reset(self):
        """Сбросить масштаб"""
        self.navigation_manager.zoom_reset()
    
    def _fit_to_view(self):
        """Подогнать к окну"""
        self.navigation_manager.fit_to_view()
    
    def _marker_segment_pdf(self):
        """Разметка текущей страницы PDF через API"""
        self.marker_manager.segment_current_page()

    def _marker_segment_all_pages(self):
        """Разметка всех страниц PDF через API"""
        self.marker_manager.segment_all_pages()
    
    def _run_ocr_all(self):
        """Запустить OCR для всех блоков"""
        self.ocr_manager.run_ocr_all()
    
    def _on_project_switched(self, project_id: str):
        """Обработка переключения проекта"""
        self._save_current_annotation_to_cache()
        
        project = self.project_manager.get_project(project_id)
        if not project:
            return
        
        active_file = project.get_active_file()
        if active_file:
            self._load_pdf_from_project(project_id, project.active_file_index)
        else:
            if self.pdf_document:
                self.pdf_document.close()
            self.pdf_document = None
            self.annotation_document = None
            self._current_project_id = project_id
            self._current_file_index = -1
            self.page_images.clear()
            self.page_zoom_states.clear()
            self.page_viewer.set_page_image(None, 0)
            self._update_ui()
    
    def _on_file_switched(self, project_id: str, file_index: int):
        """Обработка переключения файла в проекте"""
        self._save_current_annotation_to_cache()
        self._load_pdf_from_project(project_id, file_index)
