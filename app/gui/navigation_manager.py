"""
Менеджер навигации по страницам PDF
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class NavigationManager:
    """Управление навигацией по страницам"""
    
    def __init__(self, parent: 'MainWindow'):
        self.parent = parent
    
    def prev_page(self):
        """Предыдущая страница"""
        if self.parent.current_page > 0:
            self.save_current_zoom()
            self.parent.current_page -= 1
            self.parent._render_current_page()
            self.parent._update_ui()
    
    def next_page(self):
        """Следующая страница"""
        if self.parent.pdf_document and self.parent.current_page < self.parent.pdf_document.page_count - 1:
            self.save_current_zoom()
            self.parent.current_page += 1
            self.parent._render_current_page()
            self.parent._update_ui()
    
    def go_to_page(self, page_num: int):
        """Перейти на указанную страницу"""
        if self.parent.pdf_document and 0 <= page_num < self.parent.pdf_document.page_count:
            self.save_current_zoom()
            self.parent.current_page = page_num
            self.parent._render_current_page()
            self.parent._update_ui()
    
    def save_current_zoom(self):
        """Сохранить зум текущей страницы"""
        if hasattr(self.parent, '_current_pdf_path') and self.parent._current_pdf_path:
            zoom_key = (self.parent._current_pdf_path, self.parent.current_page)
            self.parent.page_zoom_states[zoom_key] = (
                self.parent.page_viewer.transform(),
                self.parent.page_viewer.zoom_factor
            )
    
    def restore_zoom(self, page_num: int = None):
        """Вписать страницу в область просмотра"""
        self.parent.page_viewer.fit_to_view()
    
    def load_page_image(self, page_num: int, reset_zoom: bool = False):
        """Загрузить изображение страницы"""
        if page_num not in self.parent.page_images:
            img = self.parent.pdf_document.render_page(page_num)
            if img:
                self.parent.page_images[page_num] = img
        
        if page_num in self.parent.page_images:
            img = self.parent.page_images[page_num]
            
            # Синхронизируем размеры Page с реальным изображением
            if self.parent.annotation_document and page_num < len(self.parent.annotation_document.pages):
                page = self.parent.annotation_document.pages[page_num]
                if page.width != img.width or page.height != img.height:
                    logger.debug(f"Обновление размеров Page {page_num}: {page.width}x{page.height} -> {img.width}x{img.height}")
                    page.width = img.width
                    page.height = img.height
            
            self.parent.page_viewer.set_page_image(img, page_num, reset_zoom=reset_zoom)
    
    def zoom_in(self):
        """Увеличить масштаб"""
        if hasattr(self.parent.page_viewer, 'scale'):
            self.parent.page_viewer.scale(1.15, 1.15)
            self.parent.page_viewer.zoom_factor *= 1.15
    
    def zoom_out(self):
        """Уменьшить масштаб"""
        if hasattr(self.parent.page_viewer, 'scale'):
            self.parent.page_viewer.scale(1/1.15, 1/1.15)
            self.parent.page_viewer.zoom_factor /= 1.15
    
    def zoom_reset(self):
        """Сбросить масштаб"""
        if hasattr(self.parent.page_viewer, 'reset_zoom'):
            self.parent.page_viewer.reset_zoom()
    
    def fit_to_view(self):
        """Подогнать к окну"""
        if hasattr(self.parent.page_viewer, 'fit_to_view'):
            self.parent.page_viewer.fit_to_view()

