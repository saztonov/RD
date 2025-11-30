"""
OCR Manager для MainWindow
Управление OCR операциями и диалогами
"""

import logging
from pathlib import Path
from PySide6.QtWidgets import QProgressDialog, QMessageBox, QDialog
from PySide6.QtCore import Qt
from app.ocr import create_ocr_engine, generate_structured_markdown, run_local_vlm_full_document, run_chandra_ocr_full_document, load_prompt
from app.annotation_io import AnnotationIO
from app.models import BlockType

logger = logging.getLogger(__name__)


class OCRManager:
    """Управление OCR операциями"""
    
    def __init__(self, parent):
        self.parent = parent
    
    def run_ocr_all(self):
        """Запустить OCR для всех блоков"""
        if not self.parent.annotation_document or not self.parent.pdf_document:
            QMessageBox.warning(self.parent, "Внимание", "Сначала откройте PDF")
            return
        
        from app.gui.ocr_dialog import OCRDialog
        
        dialog = OCRDialog(self.parent)
        if dialog.exec() != QDialog.Accepted:
            return
        
        output_dir = Path(dialog.output_dir)
        mode = dialog.mode
        
        output_dir.mkdir(parents=True, exist_ok=True)
        crops_dir = output_dir / "crops"
        crops_dir.mkdir(exist_ok=True)
        
        import shutil
        pdf_name = Path(self.parent.annotation_document.pdf_path).name
        pdf_output = output_dir / pdf_name
        shutil.copy2(self.parent.annotation_document.pdf_path, pdf_output)
        logger.info(f"PDF сохранен: {pdf_output}")
        
        if mode == "blocks":
            self.run_local_vlm_ocr_blocks_with_output(dialog.vlm_server_url, dialog.vlm_model_name, output_dir, crops_dir)
        else:
            self.run_local_vlm_ocr_with_output(dialog.vlm_server_url, dialog.vlm_model_name, output_dir)
    
    def run_local_vlm_ocr_blocks_with_output(self, api_base, model_name, output_dir, crops_dir):
        """Запустить LocalVLM OCR для блоков"""
        try:
            ocr_engine = create_ocr_engine("local_vlm", api_base=api_base, model_name=model_name)
        except Exception as e:
            QMessageBox.critical(self.parent, "Ошибка LocalVLM OCR", f"Не удалось инициализировать:\n{e}")
            return
            
        total_blocks = sum(len(p.blocks) for p in self.parent.annotation_document.pages)
        if total_blocks == 0:
            QMessageBox.information(self.parent, "Информация", "Нет блоков для OCR")
            return

        progress = QProgressDialog(f"Распознавание блоков через {model_name}...", "Отмена", 0, total_blocks, self.parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        processed_count = 0
        
        for page in self.parent.annotation_document.pages:
            if progress.wasCanceled():
                break
                
            page_num = page.page_number
            if page_num not in self.parent.page_images:
                img = self.parent.pdf_document.render_page(page_num)
                if img:
                    self.parent.page_images[page_num] = img
            
            page_img = self.parent.page_images.get(page_num)
            if not page_img:
                continue
            
            for block in page.blocks:
                if progress.wasCanceled():
                    break
                
                x1, y1, x2, y2 = block.coords_px
                if x1 >= x2 or y1 >= y2:
                    processed_count += 1
                    progress.setValue(processed_count)
                    continue
                
                crop = page_img.crop((x1, y1, x2, y2))
                
                try:
                    if block.block_type == BlockType.IMAGE:
                        crop_filename = f"page{page_num}_block{block.id}.png"
                        crop_path = crops_dir / crop_filename
                        crop.save(crop_path, "PNG")
                        block.image_file = str(crop_path)
                    
                    if block.block_type == BlockType.IMAGE:
                        image_prompt = load_prompt("ocr_image_description.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=image_prompt)
                    elif block.block_type == BlockType.TABLE:
                        table_prompt = load_prompt("ocr_table.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=table_prompt) if table_prompt else ocr_engine.recognize(crop)
                    elif block.block_type == BlockType.TEXT:
                        text_prompt = load_prompt("ocr_text.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=text_prompt) if text_prompt else ocr_engine.recognize(crop)
                        
                except Exception as e:
                    logger.error(f"Error OCR block {block.id}: {e}")
                    block.ocr_text = f"[Error: {e}]"
                
                processed_count += 1
                progress.setValue(processed_count)
        
        progress.close()
        
        json_path = output_dir / "annotation.json"
        AnnotationIO.save_annotation(self.parent.annotation_document, str(json_path))
        logger.info(f"Разметка сохранена: {json_path}")
        
        md_path = output_dir / "document.md"
        generate_structured_markdown(self.parent.annotation_document.pages, str(md_path))
        logger.info(f"Markdown сохранен: {md_path}")
        
        pdf_name = Path(self.parent.annotation_document.pdf_path).name
        QMessageBox.information(
            self.parent, 
            "Готово", 
            f"OCR завершен!\n\nРезультаты сохранены в:\n{output_dir}\n\n• {pdf_name}\n• annotation.json\n• crops/\n• document.md"
        )
    
    def run_chandra_ocr_blocks_with_output(self, method, output_dir, crops_dir):
        """Запустить Chandra OCR для блоков"""
        try:
            chandra_engine = create_ocr_engine("chandra", method=method)
            vlm_engine = create_ocr_engine("local_vlm", api_base="http://127.0.0.1:1234/v1", model_name="qwen3-vl-32b-instruct")
        except Exception as e:
            QMessageBox.critical(self.parent, "Ошибка OCR", f"Не удалось инициализировать:\n{e}")
            return
            
        total_blocks = sum(len(p.blocks) for p in self.parent.annotation_document.pages)
        if total_blocks == 0:
            QMessageBox.information(self.parent, "Информация", "Нет блоков для OCR")
            return

        progress = QProgressDialog("Распознавание блоков (Chandra + VLM)...", "Отмена", 0, total_blocks, self.parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        processed_count = 0
        
        for page in self.parent.annotation_document.pages:
            if progress.wasCanceled():
                break
                
            page_num = page.page_number
            if page_num not in self.parent.page_images:
                img = self.parent.pdf_document.render_page(page_num)
                if img:
                    self.parent.page_images[page_num] = img
            
            page_img = self.parent.page_images.get(page_num)
            if not page_img:
                continue
            
            for block in page.blocks:
                if progress.wasCanceled():
                    break
                
                x1, y1, x2, y2 = block.coords_px
                if x1 >= x2 or y1 >= y2:
                    processed_count += 1
                    progress.setValue(processed_count)
                    continue
                
                crop = page_img.crop((x1, y1, x2, y2))
                
                try:
                    if block.block_type == BlockType.IMAGE:
                        crop_filename = f"page{page_num}_block{block.id}.png"
                        crop_path = crops_dir / crop_filename
                        crop.save(crop_path, "PNG")
                        block.image_file = str(crop_path)
                        image_prompt = load_prompt("ocr_image_description.txt")
                        block.ocr_text = vlm_engine.recognize(crop, prompt=image_prompt)
                    elif block.block_type in (BlockType.TEXT, BlockType.TABLE):
                        block.ocr_text = chandra_engine.recognize(crop)
                        
                except Exception as e:
                    logger.error(f"Error OCR block {block.id}: {e}")
                    block.ocr_text = f"[Error: {e}]"
                
                processed_count += 1
                progress.setValue(processed_count)
        
        progress.close()
        
        json_path = output_dir / "annotation.json"
        AnnotationIO.save_annotation(self.parent.annotation_document, str(json_path))
        logger.info(f"Разметка сохранена: {json_path}")
        
        md_path = output_dir / "document.md"
        generate_structured_markdown(self.parent.annotation_document.pages, str(md_path))
        logger.info(f"Markdown сохранен: {md_path}")
        
        pdf_name = Path(self.parent.annotation_document.pdf_path).name
        QMessageBox.information(
            self.parent, 
            "Готово", 
            f"OCR завершен!\n\nРезультаты сохранены в:\n{output_dir}\n\n• {pdf_name}\n• annotation.json\n• crops/\n• document.md"
        )
    
    def run_local_vlm_ocr_with_output(self, api_base, model_name, output_dir):
        """Запустить LocalVLM OCR для всего документа"""
        progress = QProgressDialog("Подготовка страниц...", None, 0, len(self.parent.annotation_document.pages), self.parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        for i, page in enumerate(self.parent.annotation_document.pages):
            page_num = page.page_number
            if page_num not in self.parent.page_images:
                img = self.parent.pdf_document.render_page(page_num)
                if img:
                    self.parent.page_images[page_num] = img
            progress.setValue(i + 1)
        
        progress.close()
        
        progress = QProgressDialog(f"Распознавание с {model_name}...", None, 0, 0, self.parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        try:
            md_path = output_dir / "document.md"
            result_path = run_local_vlm_full_document(
                self.parent.page_images, 
                str(md_path), 
                api_base=api_base,
                model_name=model_name
            )
            
            json_path = output_dir / "annotation.json"
            AnnotationIO.save_annotation(self.parent.annotation_document, str(json_path))
            
            progress.close()
            
            pdf_name = Path(self.parent.annotation_document.pdf_path).name
            QMessageBox.information(
                self.parent, 
                "Успех", 
                f"OCR завершен!\n\nРезультаты сохранены в:\n{output_dir}\n\n• {pdf_name}\n• annotation.json\n• document.md"
            )
        except Exception as e:
            progress.close()
            QMessageBox.critical(self.parent, "Ошибка", f"Ошибка LocalVLM OCR:\n{e}")
    
    def run_chandra_ocr_with_output(self, method, output_dir):
        """Запустить Chandra OCR для всего документа"""
        progress = QProgressDialog("Подготовка страниц...", None, 0, len(self.parent.annotation_document.pages), self.parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        for i, page in enumerate(self.parent.annotation_document.pages):
            page_num = page.page_number
            if page_num not in self.parent.page_images:
                img = self.parent.pdf_document.render_page(page_num)
                if img:
                    self.parent.page_images[page_num] = img
            progress.setValue(i + 1)
        
        progress.close()
        
        progress = QProgressDialog("Распознавание с Chandra OCR...", None, 0, 0, self.parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        try:
            md_path = output_dir / "document.md"
            result_path = run_chandra_ocr_full_document(self.parent.page_images, str(md_path), method=method)
            
            json_path = output_dir / "annotation.json"
            AnnotationIO.save_annotation(self.parent.annotation_document, str(json_path))
            
            progress.close()
            
            pdf_name = Path(self.parent.annotation_document.pdf_path).name
            QMessageBox.information(
                self.parent, 
                "Успех", 
                f"OCR завершен!\n\nРезультаты сохранены в:\n{output_dir}\n\n• {pdf_name}\n• annotation.json\n• document.md"
            )
        except ImportError as e:
            progress.close()
            QMessageBox.critical(
                self.parent, 
                "Ошибка импорта Chandra OCR", 
                f"{e}\n\nТребуется установить chandra-ocr:\npip install chandra-ocr"
            )
        except Exception as e:
            progress.close()
            QMessageBox.critical(self.parent, "Ошибка", f"Ошибка Chandra OCR:\n{e}")

