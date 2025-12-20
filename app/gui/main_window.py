"""
Главное окно приложения
Интеграция компонентов через миксины
"""

from typing import Optional
from PySide6.QtWidgets import QMainWindow
from rd_core.models import Document, BlockType
from rd_core.pdf_utils import PDFDocument
from app.gui.blocks_tree_manager import BlocksTreeManager
from app.gui.prompt_manager import PromptManager
from app.gui.navigation_manager import NavigationManager
from app.gui.menu_setup import MenuSetupMixin
from app.gui.panels_setup import PanelsSetupMixin
from app.gui.remote_ocr_panel import RemoteOCRPanel
from app.gui.file_operations import FileOperationsMixin
from app.gui.block_handlers import BlockHandlersMixin


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
        self.page_zoom_states: dict = {}
        self._current_pdf_path: Optional[str] = None
        
        # Undo/Redo стек
        self.undo_stack: list = []  # [(page_num, blocks_copy), ...]
        self.redo_stack: list = []
        
        # Менеджеры (инициализируются после setup_ui)
        self.prompt_manager = PromptManager(self)
        self.blocks_tree_manager = None
        self.navigation_manager = None
        self.remote_ocr_panel = None
        
        # Настройка UI
        self._setup_menu()
        self._setup_toolbar()
        self._setup_ui()
        
        # Remote OCR панель
        self._setup_remote_ocr_panel()
        
        # Инициализация менеджеров после создания UI
        self.blocks_tree_manager = BlocksTreeManager(self, self.blocks_tree)
        self.navigation_manager = NavigationManager(self)
        
        # Инициализация промптов
        self.prompt_manager.ensure_default_prompts()  # Проверяем наличие промптов в R2
        
        self.setWindowTitle("PDF Annotation Tool")
        self.resize(1200, 800)
        
        # Восстановить настройки окна
        self._restore_settings()
    
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
            self.page_input.setEnabled(True)
            self.page_input.setMaximum(self.pdf_document.page_count)
            self.page_input.blockSignals(True)
            self.page_input.setValue(self.current_page + 1)
            self.page_input.blockSignals(False)
        else:
            self.page_label.setText("Страница: 0 / 0")
            self.page_input.setEnabled(False)
            self.page_input.setMaximum(1)
    
    def _prev_page(self):
        """Предыдущая страница"""
        self.navigation_manager.prev_page()
    
    def _next_page(self):
        """Следующая страница"""
        self.navigation_manager.next_page()
    
    def _goto_page_from_input(self, page_num: int):
        """Перейти на страницу из поля ввода (нумерация с 1)"""
        if self.pdf_document:
            self.navigation_manager.go_to_page(page_num - 1)
    
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
    
    def _save_undo_state(self):
        """Сохранить текущее состояние блоков для отмены"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        # Делаем глубокую копию блоков
        import copy
        blocks_copy = copy.deepcopy(current_page_data.blocks)
        
        # Добавляем в стек undo
        self.undo_stack.append((self.current_page, blocks_copy))
        
        # Ограничиваем размер стека (последние 50 операций)
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        
        # Очищаем стек redo при новом действии
        self.redo_stack.clear()
    
    def _undo(self):
        """Отменить последнее действие"""
        if not self.undo_stack:
            return
        
        if not self.annotation_document:
            return
        
        # Сохраняем текущее состояние в redo
        current_page_data = self._get_or_create_page(self.current_page)
        if current_page_data:
            import copy
            blocks_copy = copy.deepcopy(current_page_data.blocks)
            self.redo_stack.append((self.current_page, blocks_copy))
        
        # Восстанавливаем состояние из undo
        page_num, blocks_copy = self.undo_stack.pop()
        
        # Переключаемся на нужную страницу если надо
        if page_num != self.current_page:
            self.navigation_manager.save_current_zoom()
            self.current_page = page_num
            self.navigation_manager.load_page_image(self.current_page)
            self.navigation_manager.restore_zoom()
        
        # Восстанавливаем блоки
        page_data = self._get_or_create_page(page_num)
        if page_data:
            import copy
            page_data.blocks = copy.deepcopy(blocks_copy)
            self.page_viewer.set_blocks(page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
            self._update_ui()
    
    def _redo(self):
        """Повторить отменённое действие"""
        if not self.redo_stack:
            return
        
        if not self.annotation_document:
            return
        
        # Сохраняем текущее состояние в undo
        current_page_data = self._get_or_create_page(self.current_page)
        if current_page_data:
            import copy
            blocks_copy = copy.deepcopy(current_page_data.blocks)
            self.undo_stack.append((self.current_page, blocks_copy))
        
        # Восстанавливаем состояние из redo
        page_num, blocks_copy = self.redo_stack.pop()
        
        # Переключаемся на нужную страницу если надо
        if page_num != self.current_page:
            self.navigation_manager.save_current_zoom()
            self.current_page = page_num
            self.navigation_manager.load_page_image(self.current_page)
            self.navigation_manager.restore_zoom()
        
        # Восстанавливаем блоки
        page_data = self._get_or_create_page(page_num)
        if page_data:
            import copy
            page_data.blocks = copy.deepcopy(blocks_copy)
            self.page_viewer.set_blocks(page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
            self._update_ui()
    
    def _sync_from_r2(self):
        """Синхронизировать промты из R2"""
        from PySide6.QtWidgets import QMessageBox
        
        if not self.prompt_manager.r2_storage:
            QMessageBox.warning(self, "R2 недоступен", "R2 Storage не настроен. Проверьте .env файл.")
            return
        
        # Проверяем наличие промптов
        self.prompt_manager.ensure_default_prompts()
        
        QMessageBox.information(
            self,
            "Синхронизация завершена",
            "Промпты обновлены"
        )
    
    def _clear_interface(self):
        """Очистить интерфейс при отсутствии файлов"""
        if self.pdf_document:
            self.pdf_document.close()
        self.pdf_document = None
        self.annotation_document = None
        self._current_pdf_path = None
        self.page_images.clear()
        self.page_viewer.set_page_image(None, 0)
        self.page_viewer.set_blocks([])
        if self.blocks_tree_manager:
            self.blocks_tree_manager.update_blocks_tree()
        self._update_ui()
    
    def _save_settings(self):
        """Сохранить настройки окна"""
        from PySide6.QtCore import QSettings
        
        settings = QSettings("PDFAnnotationTool", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        
        if hasattr(self, 'main_splitter'):
            settings.setValue("splitterSizes", self.main_splitter.saveState())
    
    def _restore_settings(self):
        """Восстановить настройки окна"""
        from PySide6.QtCore import QSettings
        
        settings = QSettings("PDFAnnotationTool", "MainWindow")
        
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        window_state = settings.value("windowState")
        if window_state:
            self.restoreState(window_state)
        
        if hasattr(self, 'main_splitter'):
            splitter_state = settings.value("splitterSizes")
            if splitter_state:
                self.main_splitter.restoreState(splitter_state)
    
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        self._save_settings()
        event.accept()
    
    # === Remote OCR ===
    def _setup_remote_ocr_panel(self):
        """Инициализировать панель Remote OCR"""
        from PySide6.QtCore import Qt
        self.remote_ocr_panel = RemoteOCRPanel(self, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.remote_ocr_panel)
        self.resizeDocks([self.remote_ocr_panel], [520], Qt.Horizontal)
        self.remote_ocr_panel.show()  # Всегда показывать при загрузке
    
    def _toggle_remote_ocr_panel(self):
        """Показать/скрыть панель Remote OCR"""
        if self.remote_ocr_panel:
            if self.remote_ocr_panel.isVisible():
                self.remote_ocr_panel.hide()
            else:
                self.remote_ocr_panel.show()
    
    def _show_folder_settings(self):
        """Показать диалог настройки папок"""
        from app.gui.folder_settings_dialog import FolderSettingsDialog
        dialog = FolderSettingsDialog(self)
        dialog.exec()
    
    def _send_to_remote_ocr(self):
        """Отправить выделенные блоки на Remote OCR"""
        if self.remote_ocr_panel:
            self.remote_ocr_panel.show()
            self.remote_ocr_panel._create_job()
    
    def _save_draft_to_server(self):
        """Сохранить черновик (PDF + разметка) на сервере"""
        if self.remote_ocr_panel:
            self.remote_ocr_panel.show()
            self.remote_ocr_panel._save_draft()