"""
Обрезка и сохранение блоков
Сохранение кропов блоков в виде изображений в структуру папок по категориям:
output/
  category1/
    page0_block{id}.jpg
  category2/
    page1_block{id}.jpg
  неразмеченные/
    page2_block{id}.jpg
  src/
    original.pdf
    {filename}_annotations.json
"""

import json
import logging
import shutil
from pathlib import Path
from PIL import Image
from typing import List, Dict
import fitz
from app.models import PageModel, Block, Document


logger = logging.getLogger(__name__)


def export_blocks_by_category(doc_path: str, pages: List[PageModel], base_output_dir: str) -> None:
    """
    Экспортировать кропы блоков, сгруппировав по категориям
    
    Args:
        doc_path: путь к исходному PDF
        pages: список PageModel со всеми страницами
        base_output_dir: базовая директория для выходных папок по категориям
    """
    try:
        base_output_path = Path(base_output_dir)
        base_output_path.mkdir(parents=True, exist_ok=True)
        
        # Группируем блоки по категориям
        blocks_by_category: Dict[str, List[Block]] = {}
        
        for page in pages:
            for block in page.blocks:
                category = block.category if block.category else "неразмеченные"
                if category not in blocks_by_category:
                    blocks_by_category[category] = []
                blocks_by_category[category].append(block)
        
        logger.info(f"Найдено категорий: {len(blocks_by_category)}")
        
        # Открываем PDF для извлечения фрагментов
        pdf_doc = fitz.open(doc_path)
        
        # Для каждой категории создаём папку и сохраняем блоки
        for category, blocks in blocks_by_category.items():
            category_dir = base_output_path / category
            category_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Обработка категории '{category}': {len(blocks)} блоков")
            
            # Сохраняем кропы напрямую в папку категории
            for block in blocks:
                # Получаем изображение страницы
                if block.page_index >= len(pages):
                    logger.warning(f"Страница {block.page_index} для блока {block.id} не найдена")
                    continue
                
                page = pages[block.page_index]
                
                # Сохраняем PDF-фрагмент
                pdf_filename = f"page{block.page_index}_block{block.id}.pdf"
                pdf_path = category_dir / pdf_filename
                
                try:
                    # Создаём новый PDF-документ для этого блока
                    out_pdf = fitz.open()
                    pdf_page = pdf_doc[block.page_index]
                    
                    # Вставляем страницу
                    out_pdf.insert_pdf(pdf_doc, from_page=block.page_index, to_page=block.page_index)
                    out_page = out_pdf[0]
                    
                    # Получаем координаты в PDF-пространстве (нормализованные)
                    x0_norm, y0_norm, x1_norm, y1_norm = block.coords_norm
                    page_rect = pdf_page.rect
                    
                    # Преобразуем в абсолютные координаты PDF
                    crop_rect = fitz.Rect(
                        page_rect.x0 + x0_norm * page_rect.width,
                        page_rect.y0 + y0_norm * page_rect.height,
                        page_rect.x0 + x1_norm * page_rect.width,
                        page_rect.y0 + y1_norm * page_rect.height
                    )
                    
                    # Устанавливаем CropBox
                    out_page.set_cropbox(crop_rect)
                    
                    # Сохраняем PDF
                    out_pdf.save(str(pdf_path), garbage=4, deflate=True)
                    out_pdf.close()
                    
                    logger.debug(f"PDF-кроп сохранён: {pdf_path}")
                except Exception as e:
                    logger.error(f"Ошибка сохранения PDF-кропа для блока {block.id}: {e}")
                
                # Обновляем путь в блоке
                block.image_file = pdf_filename
            
            logger.info(f"Категория '{category}': {len(blocks)} кропов сохранено")
        
        # Закрываем PDF
        pdf_doc.close()
        
        # Создаём папку "src"
        docs_dir = base_output_path / "src"
        docs_dir.mkdir(parents=True, exist_ok=True)
        
        # Копируем исходный PDF
        if Path(doc_path).exists():
            pdf_filename = Path(doc_path).name
            shutil.copy2(doc_path, docs_dir / pdf_filename)
            logger.info(f"PDF скопирован в src/{pdf_filename}")
        
        # Создаём полный annotations.json со всеми блоками
        annotations_data = {
            "pdf_path": doc_path,
            "pages": []
        }
        
        for page in pages:
            page_data = {
                "page_index": page.page_index,
                "width": page.width,
                "height": page.height,
                "blocks": [block.to_dict() for block in page.blocks]
            }
            annotations_data["pages"].append(page_data)
        
        # Имя JSON с названием файла
        pdf_name = Path(doc_path).stem.replace(" ", "_")
        annotations_json_path = docs_dir / f"{pdf_name}_annotations.json"
        with open(annotations_json_path, 'w', encoding='utf-8') as f:
            json.dump(annotations_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Создан {pdf_name}_annotations.json со всеми блоками: {annotations_json_path}")
        
        total_blocks = sum(len(blocks) for blocks in blocks_by_category.values())
        logger.info(f"Экспорт завершён: {total_blocks} блоков в {len(blocks_by_category)} категориях")
    
    except Exception as e:
        logger.error(f"Ошибка экспорта блоков: {e}", exc_info=True)
        raise


class Cropper:
    """Legacy класс для совместимости с GUI (работа с Document)"""
    
    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: директория для сохранения кропов
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def save_block_crops(self, document: Document, page_images: Dict[int, Image.Image]) -> None:
        """
        Сохранить кропы всех блоков из Document
        
        Args:
            document: экземпляр Document
            page_images: словарь {page_number: PIL.Image}
        """
        try:
            for page in document.pages:
                page_num = page.page_number
                
                if page_num not in page_images:
                    logger.warning(f"Изображение для страницы {page_num} не найдено")
                    continue
                
                page_img = page_images[page_num]
                
                for block in page.blocks:
                    # Обрезаем блок
                    x1, y1, x2, y2 = block.coords_px
                    crop = page_img.crop((x1, y1, x2, y2))
                    
                    # Сохраняем
                    crop_filename = f"page{page_num}_block{block.id}.jpg"
                    crop_path = self.output_dir / crop_filename
                    crop.save(crop_path, "JPEG", quality=95)
                    
                    # Обновляем путь в блоке
                    block.image_file = crop_filename
            
            total_blocks = sum(len(page.blocks) for page in document.pages)
            logger.info(f"Сохранено {total_blocks} кропов в {self.output_dir}")
        
        except Exception as e:
            logger.error(f"Ошибка сохранения кропов: {e}")
            raise

