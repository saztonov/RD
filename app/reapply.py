"""
Перенос старой разметки на новый PDF
Адаптация координат блоков при изменении размеров страниц
"""

from typing import Optional
from app.models import Document, Page, Block, BlockSource
from app.pdf_utils import PDFDocument


class AnnotationReapplier:
    """
    Класс для переноса разметки со старого PDF на новый
    """
    
    def __init__(self, old_document: Document, new_pdf_path: str):
        """
        Args:
            old_document: старая разметка
            new_pdf_path: путь к новому PDF
        """
        self.old_document = old_document
        self.new_pdf_path = new_pdf_path
    
    def reapply(self, zoom: float = 2.0) -> Optional[Document]:
        """
        Перенести разметку на новый PDF
        
        Args:
            zoom: коэффициент масштабирования для рендеринга
        
        Returns:
            Новый Document с перенесённой разметкой или None в случае ошибки
        """
        try:
            # Открываем новый PDF
            with PDFDocument(self.new_pdf_path) as pdf:
                if not pdf.doc:
                    return None
                
                # Создаём новый документ
                new_document = Document(pdf_path=self.new_pdf_path)
                
                # Переносим страницы и блоки
                for old_page in self.old_document.pages:
                    page_num = old_page.page_number
                    
                    # Получаем размеры новой страницы
                    new_dims = pdf.get_page_dimensions(page_num, zoom)
                    if not new_dims:
                        continue
                    
                    new_width, new_height = new_dims
                    
                    # Вычисляем коэффициенты масштабирования
                    scale_x = new_width / old_page.width if old_page.width > 0 else 1.0
                    scale_y = new_height / old_page.height if old_page.height > 0 else 1.0
                    
                    # Создаём новую страницу
                    new_page = Page(
                        page_number=page_num,
                        width=new_width,
                        height=new_height
                    )
                    
                    # Переносим блоки используя нормализованные координаты
                    for old_block in old_page.blocks:
                        # Используем нормализованные координаты для переноса
                        # (они не зависят от размеров страницы)
                        new_coords_px = Block.norm_to_px(
                            old_block.coords_norm,
                            new_width,
                            new_height
                        )
                        
                        new_block = Block.create(
                            page_index=page_num,
                            coords_px=new_coords_px,
                            page_width=new_width,
                            page_height=new_height,
                            category=old_block.category,
                            block_type=old_block.block_type,
                            source=old_block.source,
                            ocr_text=old_block.ocr_text,
                            block_id=old_block.id  # сохраняем ID
                        )
                        new_page.blocks.append(new_block)
                    
                    new_document.pages.append(new_page)
                
                return new_document
                
        except Exception as e:
            print(f"Ошибка переноса разметки: {e}")
            return None

