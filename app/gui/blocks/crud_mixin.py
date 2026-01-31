"""
Миксин для CRUD операций с блоками.

Объединяет все под-миксины для работы с блоками.
"""

from rd_core.models import Page

from app.gui.blocks.auto_detection_mixin import AutoDetectionMixin
from app.gui.blocks.block_draw_mixin import BlockDrawMixin
from app.gui.blocks.block_modification_mixin import BlockModificationMixin
from app.gui.blocks.block_selection_mixin import BlockSelectionMixin
from app.gui.blocks.hint_panel_mixin import HintPanelMixin
from app.gui.blocks.validation_mixin import BlockValidationMixin


class BlockCRUDMixin(
    BlockValidationMixin,
    HintPanelMixin,
    BlockDrawMixin,
    BlockSelectionMixin,
    BlockModificationMixin,
    AutoDetectionMixin,
):
    """
    Миксин для операций CRUD с блоками.

    Объединяет функциональность:
    - BlockValidationMixin: валидация документа и блоков
    - HintPanelMixin: управление панелью подсказки и OCR preview
    - BlockDrawMixin: создание блоков через рисование
    - BlockSelectionMixin: обработка выбора блоков
    - BlockModificationMixin: удаление, перемещение блоков
    """

    def _get_or_create_page(self, page_num: int) -> Page:
        """Получить страницу или создать новую"""
        if not self.annotation_document:
            return None

        while len(self.annotation_document.pages) <= page_num:
            new_page_num = len(self.annotation_document.pages)

            # Приоритет: реальное изображение > get_page_dimensions > fallback
            if new_page_num in self.page_images:
                img = self.page_images[new_page_num]
                page = Page(
                    page_number=new_page_num, width=img.width, height=img.height
                )
            elif self.pdf_document:
                dims = self.pdf_document.get_page_dimensions(new_page_num)
                if dims:
                    page = Page(page_number=new_page_num, width=dims[0], height=dims[1])
                else:
                    page = Page(page_number=new_page_num, width=595, height=842)
            else:
                page = Page(page_number=new_page_num, width=595, height=842)

            self.annotation_document.pages.append(page)

        return self.annotation_document.pages[page_num]
