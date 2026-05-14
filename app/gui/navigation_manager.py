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

    def __init__(self, parent: "MainWindow"):
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
        if (
            self.parent.pdf_document
            and self.parent.current_page < self.parent.pdf_document.page_count - 1
        ):
            self.save_current_zoom()
            self.parent.current_page += 1
            self.parent._render_current_page()
            self.parent._update_ui()

    def go_to_page(self, page_num: int):
        """Перейти на указанную страницу"""
        if (
            self.parent.pdf_document
            and 0 <= page_num < self.parent.pdf_document.page_count
        ):
            self.save_current_zoom()
            self.parent.current_page = page_num
            self.parent._render_current_page()
            self.parent._update_ui()

    def save_current_zoom(self):
        """Сохранить зум текущей страницы"""
        if hasattr(self.parent, "_current_pdf_path") and self.parent._current_pdf_path:
            zoom_key = (self.parent._current_pdf_path, self.parent.current_page)
            self.parent.page_zoom_states[zoom_key] = (
                self.parent.page_viewer.transform(),
                self.parent.page_viewer.zoom_factor,
            )

    def restore_zoom(self, page_num: int = None):
        """Вписать страницу в область просмотра"""
        self.parent.page_viewer.fit_to_view()

    def _recalc_blocks_coords(self, page, new_width: int, new_height: int):
        """Пересчитать coords_px/polygon_points блоков для нового размера страницы."""
        from rd_core.annotation_canonicalizer import sync_block_to_page

        old_width = int(page.width) if page.width else int(new_width)
        old_height = int(page.height) if page.height else int(new_height)

        for block in page.blocks:
            sync_block_to_page(
                block,
                page_width=int(new_width),
                page_height=int(new_height),
                prefer_coords_px=False,
                old_page_width=old_width,
                old_page_height=old_height,
            )

    def load_page_image(self, page_num: int, reset_zoom: bool = False):
        """Загрузить изображение страницы с LRU-кешем"""
        # Рендерим если нет в кеше
        if page_num not in self.parent.page_images:
            img = self.parent.pdf_document.render_page(page_num)
            if img:
                self.parent.page_images[page_num] = img
                self.parent._page_images_order.append(page_num)

                # Удаляем старые страницы если превышен лимит
                while (
                    len(self.parent._page_images_order) > self.parent._page_images_max
                ):
                    oldest = self.parent._page_images_order.pop(0)
                    if oldest in self.parent.page_images and oldest != page_num:
                        del self.parent.page_images[oldest]
        else:
            # Обновляем LRU порядок
            if page_num in self.parent._page_images_order:
                self.parent._page_images_order.remove(page_num)
            self.parent._page_images_order.append(page_num)

        if page_num in self.parent.page_images:
            img = self.parent.page_images[page_num]

            # Синхронизируем размеры Page с реальным изображением
            if self.parent.annotation_document and page_num < len(
                self.parent.annotation_document.pages
            ):
                page = self.parent.annotation_document.pages[page_num]
                if page.width != img.width or page.height != img.height:
                    logger.debug(
                        f"Обновление размеров Page {page_num}: {page.width}x{page.height} -> {img.width}x{img.height}"
                    )
                    self._recalc_blocks_coords(page, img.width, img.height)
                    page.width = img.width
                    page.height = img.height

            self.parent.page_viewer.set_page_image(img, page_num, reset_zoom=reset_zoom)

    def zoom_in(self):
        """Увеличить масштаб"""
        if hasattr(self.parent.page_viewer, "scale"):
            self.parent.page_viewer.scale(1.15, 1.15)
            self.parent.page_viewer.zoom_factor *= 1.15

    def zoom_out(self):
        """Уменьшить масштаб"""
        if hasattr(self.parent.page_viewer, "scale"):
            self.parent.page_viewer.scale(1 / 1.15, 1 / 1.15)
            self.parent.page_viewer.zoom_factor /= 1.15

    def zoom_reset(self):
        """Сбросить масштаб"""
        if hasattr(self.parent.page_viewer, "reset_zoom"):
            self.parent.page_viewer.reset_zoom()

    def fit_to_view(self):
        """Подогнать к окну"""
        if hasattr(self.parent.page_viewer, "fit_to_view"):
            self.parent.page_viewer.fit_to_view()
