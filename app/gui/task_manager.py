"""
Менеджер фоновых заданий
"""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QThread
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Статус задания"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class TaskType(Enum):
    """Тип задания"""
    OCR = "ocr"
    MARKER = "marker"


@dataclass
class Task:
    """Задание для обработки"""
    id: str
    task_type: TaskType
    name: str
    pdf_path: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    max_progress: int = 100
    error_message: Optional[str] = None
    created_at: datetime = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class OCRWorker(QThread):
    """Фоновый поток для OCR с поддержкой batch-оптимизации"""
    progress = Signal(int, int)  # current, total
    finished = Signal(object)  # result
    error = Signal(str)
    
    def __init__(self, task_id, annotation_document, pdf_document, page_images, config):
        super().__init__()
        self.task_id = task_id
        self.annotation_document = annotation_document
        self.pdf_document = pdf_document
        self.page_images = page_images
        self.config = config
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        # Выбираем режим: datalab, batch или legacy
        use_datalab = self.config.get('use_datalab', False)
        use_batch = self.config.get('use_batch_ocr', True)
        
        if use_datalab:
            self._run_datalab_ocr()
        elif use_batch:
            self._run_batch_ocr()
        else:
            self._run_legacy_ocr()
    
    def _run_datalab_ocr(self):
        """
        Datalab OCR: последовательная обработка блоков.
        TEXT/TABLE собираются в батчи до 9000px, при встрече IMAGE - батч отправляется,
        затем обрабатывается картинка, и начинается новый батч.
        """
        try:
            from app.datalab_ocr import (
                concatenate_blocks, save_optimized_image, 
                DatalabOCRClient, resize_to_width,
                MAX_BLOCK_HEIGHT, TARGET_WIDTH, MAX_HEIGHT
            )
            from app.ocr import create_ocr_engine
            from app.annotation_io import AnnotationIO
            from app.models import BlockType
            from PIL import Image
            
            output_dir = Path(self.config['output_dir'])
            crops_dir = output_dir / "crops"
            crops_dir.mkdir(parents=True, exist_ok=True)
            temp_dir = output_dir / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            datalab_api_key = self.config.get('datalab_api_key', '')
            if not datalab_api_key:
                raise ValueError("DATALAB_API_KEY не указан")
            
            client = DatalabOCRClient(datalab_api_key)
            
            # Движок для IMAGE блоков (VLM)
            image_backend = self.config.get('datalab_image_backend', 'local')
            if image_backend == 'openrouter':
                import os
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.getenv("OPENROUTER_API_KEY")
                image_engine = create_ocr_engine("openrouter", api_key=api_key, 
                                                  model_name=self.config.get('image_model'))
            else:
                from app.config import get_lm_base_url
                image_engine = create_ocr_engine("local_vlm", 
                                                  model_name=self.config.get('vlm_model_name', 'qwen3-vl-32b-instruct'))
            
            prompt_loader = self.config.get('prompt_loader')
            
            # Собираем ВСЕ блоки в правильном порядке (страница → Y)
            all_items = []  # (block, page_num, crop, is_image)
            
            pages_with_blocks = {}
            for page in self.annotation_document.pages:
                if page.blocks:
                    pages_with_blocks[page.page_number] = page
            
            logger.info(f"Datalab OCR: страниц с блоками: {len(pages_with_blocks)}/{len(self.annotation_document.pages)}")
            
            for page_num in sorted(pages_with_blocks.keys()):
                page = pages_with_blocks[page_num]
                if self._cancelled:
                    return
                
                # Рендерим страницу
                if page_num not in self.page_images:
                    logger.debug(f"Рендеринг страницы {page_num} (есть {len(page.blocks)} блоков)")
                    img = self.pdf_document.render_page(page_num)
                    if img:
                        self.page_images[page_num] = img
                
                page_img = self.page_images.get(page_num)
                if not page_img:
                    continue
                
                # Сортируем блоки по Y позиции
                sorted_blocks = sorted(page.blocks, key=lambda b: b.coords_px[1])
                
                for block in sorted_blocks:
                    x1, y1, x2, y2 = block.coords_px
                    if x1 >= x2 or y1 >= y2:
                        continue
                    
                    block_height = y2 - y1
                    is_image = block.block_type == BlockType.IMAGE
                    
                    if block_height > MAX_BLOCK_HEIGHT:
                        # Делим большой блок на части
                        y_start = y1
                        part_idx = 0
                        while y_start < y2:
                            y_end = min(y_start + MAX_BLOCK_HEIGHT, y2)
                            crop = page_img.crop((x1, y_start, x2, y_end))
                            
                            if is_image:
                                # Сохраняем crop картинки
                                crop_filename = f"page{page_num}_block{block.id}_part{part_idx}.png"
                                crop_path = crops_dir / crop_filename
                                crop.save(crop_path, "PNG")
                                if part_idx == 0:
                                    block.image_file = str(crop_path)
                            
                            all_items.append((block, page_num, crop, is_image, f"{block.id}_part{part_idx}"))
                            y_start = y_end
                            part_idx += 1
                    else:
                        crop = page_img.crop((x1, y1, x2, y2))
                        
                        if is_image:
                            # Сохраняем crop картинки
                            crop_filename = f"page{page_num}_block{block.id}.png"
                            crop_path = crops_dir / crop_filename
                            crop.save(crop_path, "PNG")
                            block.image_file = str(crop_path)
                        
                        all_items.append((block, page_num, crop, is_image, block.id))
            
            total_items = len(all_items)
            image_count = sum(1 for item in all_items if item[3])
            logger.info(f"Datalab OCR: {total_items} элементов ({image_count} картинок)")
            
            if total_items == 0:
                self.finished.emit({'output_dir': str(output_dir), 'updated_pages': self.annotation_document.pages})
                return
            
            # Результирующий markdown
            final_markdown_parts = []
            batch_counter = 0
            processed_count = 0
            
            # Функция для отправки накопленных текст/таблица блоков
            def flush_text_batch(pending_crops, pending_items):
                nonlocal batch_counter, processed_count
                
                if not pending_crops:
                    return ""
                
                # Склеиваем в батчи
                batches = concatenate_blocks(pending_crops)
                logger.info(f"Datalab batch: {len(pending_crops)} элементов → {len(batches)} батчей")
                
                # Собираем промпт
                text_table_items = [(b, c, p) for b, p, c, is_img, _ in pending_items if not is_img]
                batch_prompt = self._get_datalab_prompt(text_table_items, prompt_loader) if text_table_items else None
                
                batch_results = []
                for batch_image in batches:
                    if self._cancelled:
                        return ""
                    
                    batch_path = temp_dir / f"batch_{batch_counter}.png"
                    batch_counter += 1
                    saved_path = save_optimized_image(batch_image, str(batch_path))
                    
                    try:
                        def on_poll_progress(message, attempt, max_attempts):
                            self.progress.emit(processed_count, total_items)
                        
                        markdown = client.recognize(saved_path, block_prompt=batch_prompt, progress_callback=on_poll_progress)
                        batch_results.append(markdown)
                    except Exception as e:
                        logger.error(f"Datalab batch error: {e}")
                        batch_results.append(f"[Ошибка Datalab: {e}]")
                    finally:
                        for p in [batch_path, batch_path.with_suffix('.jpg')]:
                            if p.exists():
                                p.unlink()
                
                return "\n\n".join([r for r in batch_results if r])
            
            # Функция для обработки одной картинки через VLM
            def process_image(block, crop, part_id):
                nonlocal processed_count
                
                try:
                    prompt_data = None
                    if prompt_loader:
                        if block.category:
                            prompt_data = prompt_loader(f"category_{block.category}")
                        if not prompt_data:
                            prompt_data = prompt_loader("image")
                    
                    ocr_text = image_engine.recognize(crop, prompt=prompt_data)
                    
                    # Сохраняем в блок
                    if not block.ocr_text or block.ocr_text.startswith("["):
                        block.ocr_text = ocr_text
                    elif "_part" in part_id:
                        block.ocr_text = (block.ocr_text or "") + "\n" + ocr_text
                    
                    return f"\n\n**Изображение:**\n\n{ocr_text}\n\n"
                    
                except Exception as e:
                    logger.error(f"VLM IMAGE block {part_id} error: {e}")
                    return f"\n\n**Изображение (ошибка):**\n\n[Ошибка VLM: {e}]\n\n"
            
            # Основной цикл - идём последовательно по блокам
            pending_crops = []  # накопленные кропы для текст/таблица
            pending_items = []  # соответствующие items
            current_height = 0  # текущая накопленная высота
            
            for item in all_items:
                if self._cancelled:
                    return
                
                block, page_num, crop, is_image, part_id = item
                
                if is_image:
                    # Встретили картинку - сбрасываем накопленное
                    if pending_crops:
                        md = flush_text_batch(pending_crops, pending_items)
                        if md:
                            final_markdown_parts.append(md)
                        pending_crops = []
                        pending_items = []
                        current_height = 0
                    
                    # Обрабатываем картинку через VLM
                    md = process_image(block, crop, part_id)
                    final_markdown_parts.append(md)
                    
                    processed_count += 1
                    self.progress.emit(processed_count, total_items)
                else:
                    # TEXT/TABLE - накапливаем
                    crop_resized = resize_to_width(crop, TARGET_WIDTH)
                    crop_height = crop_resized.height
                    
                    # Проверяем, поместится ли в текущий батч
                    if current_height + crop_height > MAX_HEIGHT and pending_crops:
                        # Сбрасываем текущий батч
                        md = flush_text_batch(pending_crops, pending_items)
                        if md:
                            final_markdown_parts.append(md)
                        pending_crops = []
                        pending_items = []
                        current_height = 0
                    
                    pending_crops.append(crop)
                    pending_items.append(item)
                    current_height += crop_height + 100  # padding
                    
                    processed_count += 1
                    self.progress.emit(processed_count, total_items)
            
            # Финальный сброс оставшихся блоков
            if pending_crops:
                md = flush_text_batch(pending_crops, pending_items)
                if md:
                    final_markdown_parts.append(md)
            
            # Объединяем все части markdown
            final_markdown = "\n\n---\n\n".join([p for p in final_markdown_parts if p.strip()])
            
            # Очистка temp
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            if not self._cancelled:
                self._save_datalab_results(output_dir, final_markdown)
                
        except Exception as e:
            logger.error(f"Datalab OCR Worker error: {e}", exc_info=True)
            self.error.emit(str(e))
    
    def _save_datalab_results(self, output_dir: Path, markdown_content: str):
        """Сохранение результатов Datalab OCR"""
        from app.annotation_io import AnnotationIO
        
        # Сохраняем annotation.json
        json_path = output_dir / "annotation.json"
        AnnotationIO.save_annotation(self.annotation_document, str(json_path))
        
        # Сохраняем markdown напрямую (уже собранный с правильной последовательностью)
        md_path = output_dir / "document.md"
        md_path.write_text(markdown_content, encoding='utf-8')
        logger.info(f"Markdown сохранен: {md_path}")
        
        # Загрузка в R2
        try:
            from app.r2_storage import upload_ocr_to_r2
            project_name = output_dir.name
            logger.info(f"OCRWorker: Загрузка результатов в R2 (проект: {project_name})")
            upload_ocr_to_r2(str(output_dir), project_name)
        except Exception as e:
            logger.error(f"OCRWorker: Ошибка загрузки в R2: {e}", exc_info=True)
        
        self.finished.emit({'output_dir': str(output_dir), 'updated_pages': self.annotation_document.pages})
    
    def _get_datalab_prompt(self, blocks_data, prompt_loader) -> str:
        """Собрать промпт для Datalab на основе типов блоков и категорий"""
        from app.models import BlockType
        
        if not prompt_loader:
            return None
        
        # Собираем уникальные типы и категории
        block_types = set()
        categories = set()
        
        for block, _, _ in blocks_data:
            block_types.add(block.block_type)
            if block.category:
                categories.add(block.category)
        
        # Пытаемся получить промпт категории (приоритет)
        for cat in categories:
            prompt_data = prompt_loader(f"category_{cat}")
            if prompt_data:
                user_prompt = prompt_data.get('user', '') if isinstance(prompt_data, dict) else str(prompt_data)
                if user_prompt:
                    return user_prompt
        
        # Или промпт типа блока
        type_prompts = []
        for bt in block_types:
            key = 'table' if bt == BlockType.TABLE else 'text'
            prompt_data = prompt_loader(key)
            if prompt_data:
                user_prompt = prompt_data.get('user', '') if isinstance(prompt_data, dict) else str(prompt_data)
                if user_prompt:
                    type_prompts.append(user_prompt)
        
        if type_prompts:
            return "\n".join(type_prompts)
        
        return None
    
    def _run_batch_ocr(self):
        """Оптимизированный batch OCR с экономией токенов"""
        try:
            from app.ocr_batch import BatchOCREngine, estimate_token_savings
            from app.ocr import generate_structured_markdown
            from app.annotation_io import AnnotationIO
            from app.models import BlockType
            from app.datalab_ocr import MAX_BLOCK_HEIGHT
            import httpx
            
            output_dir = Path(self.config['output_dir'])
            crops_dir = output_dir / "crops"
            crops_dir.mkdir(parents=True, exist_ok=True)
            
            # Подготовка API клиента и URL
            if self.config['backend'] == 'openrouter':
                import os
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.getenv("OPENROUTER_API_KEY")
                api_url = "https://openrouter.ai/api/v1/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                model_name = self.config.get('text_model', 'qwen/qwen3-vl-30b-a3b-instruct')
            else:
                from app.config import get_lm_base_url
                api_url = get_lm_base_url()
                headers = {"Content-Type": "application/json"}
                model_name = self.config.get('vlm_model_name', 'qwen3-vl-32b-instruct')
            
            # Собираем все блоки с кропами (отсортированы по позиции в документе)
            # Сначала собираем страницы с блоками чтобы не рендерить пустые
            pages_with_blocks = {p.page_number: p for p in self.annotation_document.pages if p.blocks}
            logger.info(f"Batch OCR: страниц с блоками: {len(pages_with_blocks)}/{len(self.annotation_document.pages)}")
            
            blocks_with_crops = []
            for page_num, page in pages_with_blocks.items():
                if self._cancelled:
                    return
                
                # Рендерим только страницы с блоками
                if page_num not in self.page_images:
                    logger.debug(f"Рендеринг страницы {page_num} (есть {len(page.blocks)} блоков)")
                    img = self.pdf_document.render_page(page_num)
                    if img:
                        self.page_images[page_num] = img
                
                page_img = self.page_images.get(page_num)
                if not page_img:
                    continue
                
                # Сортируем блоки страницы по вертикальной позиции (сверху вниз)
                sorted_blocks = sorted(page.blocks, key=lambda b: b.coords_px[1])
                
                for block in sorted_blocks:
                    x1, y1, x2, y2 = block.coords_px
                    if x1 >= x2 or y1 >= y2:
                        continue
                    
                    # Ограничиваем высоту блока
                    block_height = y2 - y1
                    if block_height > MAX_BLOCK_HEIGHT:
                        y_start = y1
                        part_idx = 0
                        while y_start < y2:
                            y_end = min(y_start + MAX_BLOCK_HEIGHT, y2)
                            crop = page_img.crop((x1, y_start, x2, y_end))
                            if block.block_type == BlockType.IMAGE:
                                crop_filename = f"page{page_num}_block{block.id}_part{part_idx}.png"
                                crop_path = crops_dir / crop_filename
                                crop.save(crop_path, "PNG")
                                block.image_file = str(crop_path)
                            blocks_with_crops.append((block, crop, page_num))
                            y_start = y_end
                            part_idx += 1
                    else:
                        crop = page_img.crop((x1, y1, x2, y2))
                        if block.block_type == BlockType.IMAGE:
                            crop_filename = f"page{page_num}_block{block.id}.png"
                            crop_path = crops_dir / crop_filename
                            crop.save(crop_path, "PNG")
                            block.image_file = str(crop_path)
                        blocks_with_crops.append((block, crop, page_num))
            
            total_blocks = len(blocks_with_crops)
            if total_blocks == 0:
                self.finished.emit({'output_dir': str(output_dir), 'updated_pages': self.annotation_document.pages})
                return
            
            # Создаем batch engine
            with httpx.Client(timeout=600.0, headers=headers) as client:
                batch_engine = BatchOCREngine(client, model_name, use_context=True)
                
                # Группируем по промпту
                prompt_loader = self.config.get('prompt_loader')
                groups = batch_engine.group_blocks_by_prompt(blocks_with_crops, prompt_loader)
                
                # Логируем экономию
                avg_batch = min(BatchOCREngine.MAX_IMAGES_PER_REQUEST, total_blocks / max(len(groups), 1))
                savings = estimate_token_savings(total_blocks, len(groups), avg_batch)
                logger.info(f"Batch OCR: {savings['baseline_requests']} → {savings['optimized_requests']} запросов "
                           f"(экономия ~{savings['savings_percent']}% токенов)")
                
                # Обрабатываем группы
                processed_count = 0
                for group in groups:
                    if self._cancelled:
                        return
                    
                    def on_batch_progress(current, total):
                        nonlocal processed_count
                        self.progress.emit(processed_count + current, total_blocks)
                    
                    results = batch_engine.process_group_batched(group, api_url, on_batch_progress)
                    
                    # Применяем результаты к блокам
                    for item in group.items:
                        if item.block.id in results:
                            item.block.ocr_text = results[item.block.id]
                    
                    processed_count += len(group.items)
                    self.progress.emit(processed_count, total_blocks)
            
            if not self._cancelled:
                self._save_results(output_dir)
                
        except Exception as e:
            logger.error(f"Batch OCR Worker error: {e}", exc_info=True)
            self.error.emit(str(e))
    
    def _run_legacy_ocr(self):
        """Legacy режим: один блок = один запрос"""
        try:
            from app.ocr import create_ocr_engine, generate_structured_markdown
            from app.annotation_io import AnnotationIO
            from app.models import BlockType
            from app.datalab_ocr import MAX_BLOCK_HEIGHT
            
            output_dir = Path(self.config['output_dir'])
            crops_dir = output_dir / "crops"
            crops_dir.mkdir(parents=True, exist_ok=True)
            
            # OCR Engine
            if self.config['backend'] == 'openrouter':
                import os
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.getenv("OPENROUTER_API_KEY")
                
                text_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=self.config.get('text_model'))
                table_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=self.config.get('table_model'))
                image_engine = create_ocr_engine("openrouter", api_key=api_key, model_name=self.config.get('image_model'))
            else:
                api_base = self.config['vlm_server_url']
                model_name = self.config['vlm_model_name']
                text_engine = table_engine = image_engine = create_ocr_engine("local_vlm", api_base=api_base, model_name=model_name)
            
            total_blocks = sum(len(p.blocks) for p in self.annotation_document.pages)
            processed_count = 0
            
            # Только страницы с блоками
            pages_with_blocks = {p.page_number: p for p in self.annotation_document.pages if p.blocks}
            logger.info(f"Legacy OCR: страниц с блоками: {len(pages_with_blocks)}/{len(self.annotation_document.pages)}")
            
            for page_num, page in pages_with_blocks.items():
                if self._cancelled:
                    break
                
                # Рендерим только страницы с блоками
                if page_num not in self.page_images:
                    logger.debug(f"Рендеринг страницы {page_num} (есть {len(page.blocks)} блоков)")
                    img = self.pdf_document.render_page(page_num)
                    if img:
                        self.page_images[page_num] = img
                
                page_img = self.page_images.get(page_num)
                if not page_img:
                    continue
                
                for block in page.blocks:
                    if self._cancelled:
                        break
                    
                    x1, y1, x2, y2 = block.coords_px
                    if x1 >= x2 or y1 >= y2:
                        processed_count += 1
                        self.progress.emit(processed_count, total_blocks)
                        continue
                    
                    try:
                        prompt_loader = self.config.get('prompt_loader')
                        prompt_text = None
                        
                        if prompt_loader:
                            if block.category:
                                prompt_text = prompt_loader(f"category_{block.category}")
                            
                            if not prompt_text:
                                if block.block_type == BlockType.IMAGE:
                                    prompt_text = prompt_loader("image")
                                elif block.block_type == BlockType.TABLE:
                                    prompt_text = prompt_loader("table")
                                elif block.block_type == BlockType.TEXT:
                                    prompt_text = prompt_loader("text")
                        
                        # Ограничиваем высоту блока
                        block_height = y2 - y1
                        if block_height > MAX_BLOCK_HEIGHT:
                            # Делим на части и объединяем результаты
                            ocr_parts = []
                            y_start = y1
                            part_idx = 0
                            while y_start < y2:
                                y_end = min(y_start + MAX_BLOCK_HEIGHT, y2)
                                crop = page_img.crop((x1, y_start, x2, y_end))
                                
                                if block.block_type == BlockType.IMAGE and part_idx == 0:
                                    crop_filename = f"page{page_num}_block{block.id}.png"
                                    crop_path = crops_dir / crop_filename
                                    crop.save(crop_path, "PNG")
                                    block.image_file = str(crop_path)
                                
                                if block.block_type == BlockType.IMAGE:
                                    part_text = image_engine.recognize(crop, prompt=prompt_text)
                                elif block.block_type == BlockType.TABLE:
                                    part_text = table_engine.recognize(crop, prompt=prompt_text)
                                elif block.block_type == BlockType.TEXT:
                                    part_text = text_engine.recognize(crop, prompt=prompt_text)
                                else:
                                    part_text = ""
                                
                                ocr_parts.append(part_text)
                                y_start = y_end
                                part_idx += 1
                            
                            block.ocr_text = "\n".join(ocr_parts)
                        else:
                            crop = page_img.crop((x1, y1, x2, y2))
                            
                            if block.block_type == BlockType.IMAGE:
                                crop_filename = f"page{page_num}_block{block.id}.png"
                                crop_path = crops_dir / crop_filename
                                crop.save(crop_path, "PNG")
                                block.image_file = str(crop_path)
                            
                            if block.block_type == BlockType.IMAGE:
                                block.ocr_text = image_engine.recognize(crop, prompt=prompt_text)
                            elif block.block_type == BlockType.TABLE:
                                block.ocr_text = table_engine.recognize(crop, prompt=prompt_text)
                            elif block.block_type == BlockType.TEXT:
                                block.ocr_text = text_engine.recognize(crop, prompt=prompt_text)
                    except Exception as e:
                        logger.error(f"Error OCR block {block.id}: {e}")
                        block.ocr_text = f"[Error: {e}]"
                    
                    processed_count += 1
                    self.progress.emit(processed_count, total_blocks)
            
            if not self._cancelled:
                self._save_results(output_dir)
            
        except Exception as e:
            logger.error(f"OCR Worker error: {e}", exc_info=True)
            self.error.emit(str(e))
    
    def _save_results(self, output_dir: Path):
        """Сохранение результатов OCR"""
        from app.ocr import generate_structured_markdown
        from app.annotation_io import AnnotationIO
        
        json_path = output_dir / "annotation.json"
        AnnotationIO.save_annotation(self.annotation_document, str(json_path))
        
        md_path = output_dir / "document.md"
        generate_structured_markdown(self.annotation_document.pages, str(md_path))
        
        try:
            from app.r2_storage import upload_ocr_to_r2
            project_name = output_dir.name
            logger.info(f"OCRWorker: Загрузка результатов в R2 (проект: {project_name})")
            upload_ocr_to_r2(str(output_dir), project_name)
        except Exception as e:
            logger.error(f"OCRWorker: Ошибка загрузки в R2: {e}", exc_info=True)
        
        self.finished.emit({'output_dir': str(output_dir), 'updated_pages': self.annotation_document.pages})


class MarkerWorker(QThread):
    """Фоновый поток для Marker"""
    progress = Signal(int, int)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, task_id, pdf_path, pages, page_images, page_range, category, engine="paddle"):
        super().__init__()
        self.task_id = task_id
        self.pdf_path = pdf_path
        self.pages = pages
        self.page_images = page_images
        self.page_range = page_range
        self.category = category
        self.engine = engine
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        try:
            if self._cancelled:
                return
            
            from app.segmentation_api import segment_with_api
            result = segment_with_api(
                self.pdf_path, self.pages, self.page_images, 
                self.page_range, self.category, self.engine
            )
            
            if not self._cancelled:
                self.finished.emit(result)
        except Exception as e:
            logger.error(f"Marker Worker error: {e}", exc_info=True)
            self.error.emit(str(e))


class TaskManager(QObject):
    """Менеджер фоновых заданий"""
    
    task_added = Signal(str)  # task_id
    task_updated = Signal(str)  # task_id
    task_completed = Signal(str)  # task_id
    task_failed = Signal(str, str)  # task_id, error_message
    
    def __init__(self):
        super().__init__()
        self.tasks: Dict[str, Task] = {}
        self.workers: Dict[str, QThread] = {}
        self._task_counter = 0
    
    def create_task(self, task_type: TaskType, name: str, pdf_path: str) -> str:
        """Создать новое задание"""
        self._task_counter += 1
        task_id = f"{task_type.value}_{self._task_counter}_{datetime.now().strftime('%H%M%S')}"
        
        task = Task(
            id=task_id,
            task_type=task_type,
            name=name,
            pdf_path=pdf_path
        )
        
        self.tasks[task_id] = task
        self.task_added.emit(task_id)
        return task_id
    
    def start_ocr_task(self, task_id: str, annotation_document, pdf_document, page_images, config):
        """Запустить OCR задание"""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.status = TaskStatus.RUNNING
        task.max_progress = sum(len(p.blocks) for p in annotation_document.pages)
        self.task_updated.emit(task_id)
        
        worker = OCRWorker(task_id, annotation_document, pdf_document, page_images, config)
        worker.progress.connect(lambda current, total: self._on_progress(task_id, current, total))
        worker.finished.connect(lambda result: self._on_task_finished(task_id, result))
        worker.error.connect(lambda error: self._on_task_error(task_id, error))
        
        self.workers[task_id] = worker
        worker.start()
    
    def start_marker_task(self, task_id: str, pdf_path, pages, page_images, page_range, category, engine="paddle"):
        """Запустить Marker задание"""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.status = TaskStatus.RUNNING
        self.task_updated.emit(task_id)
        
        worker = MarkerWorker(task_id, pdf_path, pages, page_images, page_range, category, engine)
        worker.finished.connect(lambda result: self._on_task_finished(task_id, result))
        worker.error.connect(lambda error: self._on_task_error(task_id, error))
        
        self.workers[task_id] = worker
        worker.start()
    
    def cancel_task(self, task_id: str):
        """Отменить задание"""
        if task_id in self.workers:
            worker = self.workers[task_id]
            if hasattr(worker, 'cancel'):
                worker.cancel()
            worker.quit()
            worker.wait()
            del self.workers[task_id]
        
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.CANCELLED
            self.task_updated.emit(task_id)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Получить задание по ID"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self):
        """Получить все задания"""
        return list(self.tasks.values())
    
    def _on_progress(self, task_id: str, current: int, total: int):
        """Обработка прогресса задания"""
        if task_id in self.tasks:
            self.tasks[task_id].progress = current
            self.tasks[task_id].max_progress = total
            self.task_updated.emit(task_id)
    
    def _on_task_finished(self, task_id: str, result):
        """Обработка завершения задания"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.SUCCESS
            self.tasks[task_id].completed_at = datetime.now()
            self.tasks[task_id].result = result
            # Принудительно ставим 100% при успешном завершении
            self.tasks[task_id].progress = self.tasks[task_id].max_progress
            self.task_completed.emit(task_id)
            self.task_updated.emit(task_id)
        
        if task_id in self.workers:
            del self.workers[task_id]
    
    def _on_task_error(self, task_id: str, error_message: str):
        """Обработка ошибки задания"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.ERROR
            self.tasks[task_id].error_message = error_message
            self.tasks[task_id].completed_at = datetime.now()
            self.task_failed.emit(task_id, error_message)
            self.task_updated.emit(task_id)
        
        if task_id in self.workers:
            del self.workers[task_id]

