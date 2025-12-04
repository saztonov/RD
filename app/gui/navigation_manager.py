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
        if self.parent._current_project_id and self.parent._current_file_index >= 0:
            zoom_key = (self.parent._current_project_id, self.parent._current_file_index, self.parent.current_page)
            self.parent.page_zoom_states[zoom_key] = (
                self.parent.page_viewer.transform(),
                self.parent.page_viewer.zoom_factor
            )
    
    def restore_zoom(self, page_num: int = None):
        """Восстановить zoom для страницы"""
        if page_num is None:
            page_num = self.parent.current_page
        
        if not self.parent._current_project_id or self.parent._current_file_index < 0:
            self.parent.page_viewer.resetTransform()
            self.parent.page_viewer.zoom_factor = 1.0
            return
        
        zoom_key = (self.parent._current_project_id, self.parent._current_file_index, page_num)
        
        if zoom_key in self.parent.page_zoom_states:
            saved_transform, saved_zoom = self.parent.page_zoom_states[zoom_key]
            self.parent.page_viewer.setTransform(saved_transform)
            self.parent.page_viewer.zoom_factor = saved_zoom
        else:
            # Попробовать найти зум для другой страницы в этом файле
            file_zooms = {k: v for k, v in self.parent.page_zoom_states.items() 
                         if k[0] == self.parent._current_project_id and k[1] == self.parent._current_file_index}
            
            if file_zooms:
                # Берем зум последней просмотренной страницы
                last_page_key = max(file_zooms.keys(), key=lambda x: x[2])
                saved_transform, saved_zoom = file_zooms[last_page_key]
                self.parent.page_viewer.setTransform(saved_transform)
                self.parent.page_viewer.zoom_factor = saved_zoom
            else:
                self.parent.page_viewer.resetTransform()
                self.parent.page_viewer.zoom_factor = 1.0
    
    def load_page_image(self, page_num: int, reset_zoom: bool = False):
        """Загрузить изображение страницы"""
        if page_num not in self.parent.page_images:
            img = self.parent.pdf_document.render_page(page_num)
            if img:
                self.parent.page_images[page_num] = img
        
        if page_num in self.parent.page_images:
            self.parent.page_viewer.set_page_image(
                self.parent.page_images[page_num], page_num, reset_zoom=reset_zoom
            )
    
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

