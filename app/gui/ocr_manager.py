"""
OCR Manager для MainWindow
Управление OCR операциями и диалогами
"""

import logging
import copy
from pathlib import Path
from PySide6.QtWidgets import QProgressDialog, QMessageBox, QDialog
from PySide6.QtCore import Qt
from app.ocr import create_ocr_engine, generate_structured_markdown, run_local_vlm_full_document, load_prompt
from app.annotation_io import AnnotationIO
from app.models import BlockType
from app.gui.task_manager import TaskManager, TaskType
from app.r2_storage import upload_ocr_to_r2

logger = logging.getLogger(__name__)


class OCRManager:
    """Управление OCR операциями"""
    
    def __init__(self, parent, task_manager: TaskManager = None):
        self.parent = parent
        self.task_manager = task_manager
    
    def _upload_to_r2(self, output_dir: Path):
        """Загрузить результаты в R2 Storage"""
        logger.info("=" * 60)
        logger.info("=== OCRManager: Вызов метода _upload_to_r2 ===")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Output directory exists: {output_dir.exists()}")
        
        try:
            project_name = output_dir.name
            logger.info(f"Project name: {project_name}")
            logger.info(f"Вызов upload_ocr_to_r2('{output_dir}', '{project_name}')")
            
            result = upload_ocr_to_r2(str(output_dir), project_name)
            
            if result:
                logger.info("✅ Результаты успешно загружены в R2")
            else:
                logger.warning("⚠️ Не удалось загрузить результаты в R2 (проверьте .env и логи выше)")
                
        except ValueError as e:
            logger.error(f"❌ Ошибка инициализации R2 (проверьте .env файл): {e}")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка загрузки в R2: {type(e).__name__}: {e}", exc_info=True)
    
    def run_ocr_all(self):
        """Запустить OCR для всех блоков (в фоне)"""
        if not self.parent.annotation_document or not self.parent.pdf_document:
            QMessageBox.warning(self.parent, "Внимание", "Сначала откройте PDF")
            return
        
        # Получаем имя задачи из активного проекта
        task_name = ""
        active_project = self.parent.project_manager.get_active_project()
        if active_project:
            task_name = active_project.name
        
        from app.gui.ocr_dialog import OCRDialog
        
        dialog = OCRDialog(self.parent, task_name=task_name)
        if dialog.exec() != QDialog.Accepted:
            return
        
        output_dir = Path(dialog.output_dir)
        mode = dialog.mode
        backend = dialog.ocr_backend
        
        output_dir.mkdir(parents=True, exist_ok=True)
        crops_dir = output_dir / "crops"
        crops_dir.mkdir(exist_ok=True)
        
        import shutil
        pdf_name = Path(self.parent.annotation_document.pdf_path).name
        pdf_output = output_dir / pdf_name
        shutil.copy2(self.parent.annotation_document.pdf_path, pdf_output)
        logger.info(f"PDF сохранен: {pdf_output}")
        
        # Используем TaskManager для фонового выполнения
        if self.task_manager and mode == "blocks":
            self._run_ocr_background(output_dir, crops_dir, dialog)
            return
        
        # Fallback на старую реализацию для full_page режима
        if backend == "openrouter":
            if mode == "blocks":
                self.run_openrouter_ocr_blocks_with_output(
                    output_dir, crops_dir, 
                    dialog.text_model, dialog.table_model, dialog.image_model
                )
            else:
                self.run_openrouter_ocr_with_output(output_dir, dialog.openrouter_model)
        else:
            if mode == "blocks":
                self.run_local_vlm_ocr_blocks_with_output(
                    dialog.vlm_server_url, dialog.vlm_model_name, output_dir, crops_dir,
                    dialog.text_model, dialog.table_model, dialog.image_model
                )
            else:
                self.run_local_vlm_ocr_with_output(dialog.vlm_server_url, dialog.vlm_model_name, output_dir)
    
    def _run_ocr_background(self, output_dir: Path, crops_dir: Path, dialog):
        """Запуск OCR в фоновом режиме через TaskManager"""
        pdf_name = Path(self.parent.annotation_document.pdf_path).stem
        task_id = self.task_manager.create_task(
            TaskType.OCR,
            f"OCR: {pdf_name}",
            self.parent.annotation_document.pdf_path
        )
        
        # Подготовка конфига
        config = {
            'output_dir': str(output_dir),
            'crops_dir': str(crops_dir),
            'backend': dialog.ocr_backend,
            'vlm_server_url': dialog.vlm_server_url,
            'vlm_model_name': dialog.vlm_model_name,
            'text_model': dialog.text_model,
            'table_model': dialog.table_model,
            'image_model': dialog.image_model,
        }
        
        # Глубокая копия документа для потока
        annotation_copy = copy.deepcopy(self.parent.annotation_document)
        page_images_copy = dict(self.parent.page_images)
        
        # Сохраняем контекст файла при запуске задачи
        task_project_id = self.parent._current_project_id
        task_file_index = self.parent._current_file_index
        task_pdf_path = self.parent.annotation_document.pdf_path
        
        # Подключаем обработчик завершения
        def on_completed(tid):
            if tid == task_id:
                task = self.task_manager.get_task(tid)
                if task and task.result:
                    result = task.result
                    if 'updated_pages' not in result:
                        return
                    
                    updated_pages = result['updated_pages']
                    
                    # Проверяем, тот ли файл сейчас активен
                    is_same_file = (
                        self.parent._current_project_id == task_project_id and
                        self.parent._current_file_index == task_file_index
                    )
                    
                    if is_same_file:
                        # Обновляем текущий документ
                        self.parent.annotation_document.pages = updated_pages
                        self.parent._render_current_page()
                        self.parent.blocks_tree_manager.update_blocks_tree()
                    else:
                        # Обновляем в кеше, если есть
                        cache_key = (task_project_id, task_file_index)
                        if cache_key in self.parent.annotations_cache:
                            self.parent.annotations_cache[cache_key].pages = updated_pages
                    
                    QMessageBox.information(
                        self.parent, 
                        "Готово", 
                        f"OCR завершен!\n\nРезультаты: {result.get('output_dir', output_dir)}"
                    )
        
        def on_failed(tid, error):
            if tid == task_id:
                QMessageBox.critical(self.parent, "Ошибка OCR", f"Ошибка:\n{error}")
        
        self.task_manager.task_completed.connect(on_completed)
        self.task_manager.task_failed.connect(on_failed)
        
        # Запуск
        self.task_manager.start_ocr_task(
            task_id,
            annotation_copy,
            self.parent.pdf_document,
            page_images_copy,
            config
        )
    
    def run_local_vlm_ocr_blocks_with_output(self, api_base, model_name, output_dir, crops_dir, 
                                             text_model=None, table_model=None, image_model=None):
        """Запустить LocalVLM OCR для блоков (для локального сервера используется одна модель)"""
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
                    
                    # Загружаем промты из R2 или используем локальные
                    if block.block_type == BlockType.IMAGE:
                        image_prompt = self.parent.prompt_manager.load_prompt("image") or load_prompt("ocr_image_description.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=image_prompt)
                    elif block.block_type == BlockType.TABLE:
                        table_prompt = self.parent.prompt_manager.load_prompt("table") or load_prompt("ocr_table.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=table_prompt) if table_prompt else ocr_engine.recognize(crop)
                    elif block.block_type == BlockType.TEXT:
                        text_prompt = self.parent.prompt_manager.load_prompt("text") or load_prompt("ocr_text.txt")
                        block.ocr_text = ocr_engine.recognize(crop, prompt=text_prompt) if text_prompt else ocr_engine.recognize(crop)
                    
                    # Дополнительный промт для категории
                    if block.category:
                        category_prompt = self.parent.prompt_manager.load_prompt(f"category_{block.category}")
                        if category_prompt:
                            logger.debug(f"Применен промт категории '{block.category}'")
                            # Можно добавить контекст категории к промту
                        
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
        
        # Загрузка в R2
        self._upload_to_r2(output_dir)
        
        pdf_name = Path(self.parent.annotation_document.pdf_path).name
        QMessageBox.information(
            self.parent, 
            "Готово", 
            f"OCR завершен!\n\nРезультаты сохранены в:\n{output_dir}\n\n• {pdf_name}\n• annotation.json\n• crops/\n• document.md"
        )
    
    def run_openrouter_ocr_blocks_with_output(self, output_dir, crops_dir, text_model, table_model, image_model):
        """Запустить OpenRouter OCR для блоков"""
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            QMessageBox.critical(self.parent, "Ошибка", "OPENROUTER_API_KEY не найден в .env файле")
            return
        
        try:
            text_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=text_model)
            table_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=table_model)
            image_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=image_model)
        except Exception as e:
            QMessageBox.critical(self.parent, "Ошибка OpenRouter OCR", f"Не удалось инициализировать:\n{e}")
            return
            
        total_blocks = sum(len(p.blocks) for p in self.parent.annotation_document.pages)
        if total_blocks == 0:
            QMessageBox.information(self.parent, "Информация", "Нет блоков для OCR")
            return

        progress = QProgressDialog("Распознавание блоков через OpenRouter...", "Отмена", 0, total_blocks, self.parent)
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
                    
                    # Загружаем промты из R2 или используем локальные
                    if block.block_type == BlockType.IMAGE:
                        image_prompt = self.parent.prompt_manager.load_prompt("image") or load_prompt("ocr_image_description.txt")
                        block.ocr_text = image_engine.recognize(crop, prompt=image_prompt)
                    elif block.block_type == BlockType.TABLE:
                        table_prompt = self.parent.prompt_manager.load_prompt("table") or load_prompt("ocr_table.txt")
                        block.ocr_text = table_engine.recognize(crop, prompt=table_prompt) if table_prompt else table_engine.recognize(crop)
                    elif block.block_type == BlockType.TEXT:
                        text_prompt = self.parent.prompt_manager.load_prompt("text") or load_prompt("ocr_text.txt")
                        block.ocr_text = text_engine.recognize(crop, prompt=text_prompt) if text_prompt else text_engine.recognize(crop)
                    
                    # Дополнительный промт для категории
                    if block.category:
                        category_prompt = self.parent.prompt_manager.load_prompt(f"category_{block.category}")
                        if category_prompt:
                            logger.debug(f"Применен промт категории '{block.category}'")
                        
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
        
        # Загрузка в R2
        self._upload_to_r2(output_dir)
        
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
            
            # Загрузка в R2
            self._upload_to_r2(output_dir)
            
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
    
    def run_openrouter_ocr_with_output(self, output_dir, model_name):
        """Запустить OpenRouter OCR для всего документа"""
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            QMessageBox.critical(self.parent, "Ошибка", "OPENROUTER_API_KEY не найден в .env файле")
            return
        
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
            from app.ocr import create_ocr_engine
            ocr_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=model_name)
            
            import base64
            from io import BytesIO
            
            md_parts = []
            for page_num, page_img in sorted(self.parent.page_images.items()):
                buffer = BytesIO()
                page_img.save(buffer, format="PNG")
                image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
                
                text = ocr_engine.recognize(page_img)
                md_parts.append(f"# Страница {page_num}\n\n{text}\n\n---\n")
            
            md_path = output_dir / "document.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(md_parts))
            
            json_path = output_dir / "annotation.json"
            AnnotationIO.save_annotation(self.parent.annotation_document, str(json_path))
            
            # Загрузка в R2
            self._upload_to_r2(output_dir)
            
            progress.close()
            
            pdf_name = Path(self.parent.annotation_document.pdf_path).name
            QMessageBox.information(
                self.parent, 
                "Успех", 
                f"OCR завершен!\n\nРезультаты сохранены в:\n{output_dir}\n\n• {pdf_name}\n• annotation.json\n• document.md"
            )
        except Exception as e:
            progress.close()
            QMessageBox.critical(self.parent, "Ошибка", f"Ошибка OpenRouter OCR:\n{e}")
    

