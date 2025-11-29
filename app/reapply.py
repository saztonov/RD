"""
Перенос старой разметки на новый PDF
Адаптация координат блоков при изменении размеров страниц
"""

import json
import fitz
from typing import Optional
from pathlib import Path
from app.models import Document, Page, Block, BlockSource, PageModel
from app.pdf_utils import PDFDocument, render_page_to_image, open_pdf


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


def transfer_annotations_to_new_pdf(
    old_annotations_path: str, 
    new_pdf_path: str, 
    zoom: float = 2.0
) -> tuple[fitz.Document, list[PageModel]]:
    """
    Перенос разметки из старого annotations.json на новый PDF
    
    Args:
        old_annotations_path: путь к старому annotations.json
        new_pdf_path: путь к новому PDF-файлу
        zoom: коэффициент масштабирования для рендеринга (default: 2.0)
    
    Returns:
        tuple[fitz.Document, list[PageModel]]: новый PDF документ и список PageModel с перенесёнными блоками
    
    Raises:
        FileNotFoundError: если файлы не найдены
        json.JSONDecodeError: если JSON некорректен
        Exception: другие ошибки
    """
    # Загрузить старый annotations.json
    annotations_file = Path(old_annotations_path)
    if not annotations_file.exists():
        raise FileNotFoundError(f"Файл разметки не найден: {old_annotations_path}")
    
    with open(old_annotations_path, 'r', encoding='utf-8') as f:
        old_data = json.load(f)
    
    # Открыть новый PDF
    new_doc = open_pdf(new_pdf_path)
    
    # Отрендерить страницы нового PDF
    new_pages: list[PageModel] = []
    
    for page_data in old_data.get("pages", []):
        page_index = page_data.get("page_index")
        if page_index is None:
            page_index = page_data.get("page_number")
        
        if page_index is None:
            continue
            
        # Проверить, что страница существует в новом PDF
        if page_index >= len(new_doc):
            print(f"Предупреждение: страница {page_index} отсутствует в новом PDF, пропускается")
            continue
        
        # Рендерить страницу нового PDF
        new_image = render_page_to_image(new_doc, page_index, zoom)
        
        # Создать PageModel
        page_model = PageModel(
            page_index=page_index,
            image=new_image,
            blocks=[]
        )
        
        # Перенести блоки
        for block_data in page_data.get("blocks", []):
            # Взять нормализованные координаты из старого JSON
            coords_norm = tuple(block_data["coords_norm"])
            
            # Рассчитать новые coords_px по размеру изображения новой страницы
            new_coords_px = Block.norm_to_px(
                coords_norm,
                new_image.width,
                new_image.height
            )
            
            # Создать новый Block с пустыми image_file и ocr_text
            new_block = Block.create(
                page_index=page_index,
                coords_px=new_coords_px,
                page_width=new_image.width,
                page_height=new_image.height,
                category=block_data.get("category", ""),
                block_type=BlockType(block_data["block_type"]),
                source=BlockSource(block_data["source"]),
                image_file=None,  # пустой
                ocr_text=None,  # пустой
                block_id=block_data.get("id")  # сохранить ID
            )
            
            page_model.blocks.append(new_block)
        
        new_pages.append(page_model)
    
    return new_doc, new_pages

