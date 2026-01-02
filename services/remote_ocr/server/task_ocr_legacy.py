"""Legacy OCR алгоритм (все в памяти)"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict

from .storage import Job, is_job_paused, update_job_status
from .rate_limiter import get_global_ocr_semaphore
from .worker_prompts import (
    fill_image_prompt_variables,
    inject_pdfplumber_to_ocr_text,
    build_strip_prompt,
    parse_batch_response_by_index,
)
from .worker_pdf import extract_pdfplumber_text_for_block
from .memory_utils import log_memory_delta, log_pil_images_summary
from .settings import settings

logger = logging.getLogger(__name__)


def run_legacy_ocr(
    job: Job,
    pdf_path: Path,
    blocks: list,
    crops_dir: Path,
    strip_backend,
    image_backend,
    stamp_backend,
    start_mem: float,
):
    """Старый алгоритм OCR (все в памяти)"""
    from .pdf_streaming import streaming_crop_and_merge
    
    logger.info("Используется старый алгоритм (все в памяти)")
    
    strip_paths, strip_images, strips, image_blocks, image_pdf_paths = streaming_crop_and_merge(
        str(pdf_path), blocks, str(crops_dir), save_image_crops_as_pdf=True
    )
    
    logger.info(f"Создано {len(strips)} полос TEXT/TABLE, {len(image_blocks)} IMAGE блоков")
    log_memory_delta("После crop_and_merge", start_mem)
    log_pil_images_summary(strip_images, "strip_images")
    
    total_requests = len(strips) + len(image_blocks)
    processed = 0
    
    def _update_progress():
        nonlocal processed
        processed += 1
        if total_requests > 0:
            progress = 0.1 + 0.8 * (processed / total_requests)
            if not is_job_paused(job.id):
                update_job_status(job.id, "processing", progress=progress)
    
    global_sem = get_global_ocr_semaphore(settings.max_global_ocr_requests)
    max_workers = settings.ocr_threads_per_job
    
    # Обработка TEXT/TABLE полос
    text_block_parts: Dict[str, Dict[int, str]] = {}
    text_block_total_parts: Dict[str, int] = {}
    text_block_objects: Dict[str, object] = {}
    
    def _process_strip(strip_idx: int, strip):
        try:
            logger.info(f"Обработка полосы {strip_idx + 1}/{len(strips)}: {len(strip.blocks)} блоков")
            merged_image = strip_images.get(strip.strip_id)
            if not merged_image:
                return {}, []
            
            prompt_data = build_strip_prompt(strip.blocks)
            
            global_sem.acquire()
            try:
                response_text = strip_backend.recognize(merged_image, prompt=prompt_data)
            finally:
                global_sem.release()
            
            index_results = parse_batch_response_by_index(len(strip.blocks), response_text)
            return index_results, strip.block_parts
            
        except Exception as e:
            logger.error(f"Ошибка обработки полосы {strip_idx + 1}: {e}", exc_info=True)
            return {}, []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        strip_futures = {executor.submit(_process_strip, idx, strip): strip for idx, strip in enumerate(strips)}
        
        for future in as_completed(strip_futures):
            strip = strip_futures[future]
            try:
                index_results, block_parts_info = future.result()
                
                if block_parts_info and len(block_parts_info) == len(strip.blocks):
                    for i, block_part in enumerate(block_parts_info):
                        text = index_results.get(i, "")
                        block = block_part.block
                        block_id = block.id
                        part_idx = block_part.part_idx
                        total_parts = block_part.total_parts
                        
                        if block_id not in text_block_parts:
                            text_block_parts[block_id] = {}
                            text_block_total_parts[block_id] = total_parts
                            text_block_objects[block_id] = block
                        
                        text_block_parts[block_id][part_idx] = text
                else:
                    seen_blocks = set()
                    for i, block in enumerate(strip.blocks):
                        if block.id not in seen_blocks:
                            text = index_results.get(i, "")
                            block.ocr_text = text
                            logger.debug(f"OCR результат для блока {block.id}: {len(text) if text else 0} символов")
                            seen_blocks.add(block.id)
            except Exception as e:
                logger.error(f"Ошибка получения результата полосы: {e}")
            finally:
                _update_progress()
    
    # Сборка TEXT/TABLE результатов
    for block_id, parts_dict in text_block_parts.items():
        block = text_block_objects[block_id]
        total_parts = text_block_total_parts[block_id]
        
        if total_parts == 1:
            block.ocr_text = parts_dict.get(0, "")
        else:
            combined_parts = [parts_dict.get(i, "") for i in range(total_parts)]
            block.ocr_text = "\n\n".join(combined_parts)
        logger.info(f"TEXT блок {block_id}: ocr_text длина = {len(block.ocr_text) if block.ocr_text else 0}")
    
    # Обработка IMAGE блоков
    block_parts_results: Dict[str, Dict[int, str]] = {}
    block_total_parts: Dict[str, int] = {}
    block_objects: Dict[str, object] = {}
    
    def _process_image_block(img_idx: int, block, crop, part_idx: int, total_parts: int):
        try:
            part_info = f" (часть {part_idx + 1}/{total_parts})" if total_parts > 1 else ""
            logger.info(f"Обработка IMAGE блока {img_idx + 1}/{len(image_blocks)}: {block.id}{part_info}")
            
            pdfplumber_text = extract_pdfplumber_text_for_block(str(pdf_path), block.page_index, block.coords_norm)
            doc_name = pdf_path.name
            
            # Получаем category_id и category_code из блока
            category_id = getattr(block, 'category_id', None)
            category_code = getattr(block, 'category_code', None)
            
            prompt_data = fill_image_prompt_variables(
                prompt_data=block.prompt,
                doc_name=doc_name,
                page_index=block.page_index,
                block_id=block.id,
                hint=getattr(block, 'hint', None),
                pdfplumber_text=pdfplumber_text,
                category_id=category_id,
                category_code=category_code
            )
            
            # Выбираем backend в зависимости от кода блока
            block_code = getattr(block, 'code', None)
            backend = stamp_backend if block_code == 'stamp' else image_backend
            
            global_sem.acquire()
            try:
                text = backend.recognize(crop, prompt=prompt_data)
            finally:
                global_sem.release()
            text = inject_pdfplumber_to_ocr_text(text, pdfplumber_text)
            
            block.pdfplumber_text = pdfplumber_text
            
            return block.id, text, part_idx, total_parts
            
        except Exception as e:
            logger.error(f"Ошибка OCR для IMAGE блока {block.id}: {e}")
            return block.id, f"[Ошибка: {e}]", part_idx, total_parts
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        image_futures = {
            executor.submit(_process_image_block, idx, block, crop, part_idx, total_parts): (block, part_idx, total_parts)
            for idx, (block, crop, part_idx, total_parts) in enumerate(image_blocks)
        }
        
        for future in as_completed(image_futures):
            block, part_idx, total_parts = image_futures[future]
            try:
                block_id, text, res_part_idx, res_total_parts = future.result()
                
                if block_id not in block_parts_results:
                    block_parts_results[block_id] = {}
                    block_total_parts[block_id] = res_total_parts
                    block_objects[block_id] = block
                
                block_parts_results[block_id][res_part_idx] = text
            except Exception as e:
                logger.error(f"Ошибка получения результата IMAGE: {e}")
                block.ocr_text = f"[Ошибка: {e}]"
            finally:
                _update_progress()
    
    # Сборка IMAGE результатов
    for block_id, parts_dict in block_parts_results.items():
        block = block_objects[block_id]
        total_parts = block_total_parts[block_id]
        
        if total_parts == 1:
            block.ocr_text = parts_dict.get(0, "")
        else:
            combined_parts = [parts_dict.get(i, "") for i in range(total_parts)]
            block.ocr_text = "\n\n".join(combined_parts)
        logger.info(f"IMAGE блок {block_id}: ocr_text длина = {len(block.ocr_text) if block.ocr_text else 0}")
    
    logger.info(f"OCR завершён: {processed} запросов обработано")
    log_memory_delta("После OCR обработки", start_mem)
    
    # Освобождаем память
    for strip in strips:
        for crop in strip.crops:
            try:
                crop.close()
            except:
                pass
        strip.crops.clear()
    for strip_id, strip_img in list(strip_images.items()):
        try:
            strip_img.close()
        except:
            pass
    strip_images.clear()
    
    for block, crop, part_idx, total_parts in image_blocks:
        try:
            crop.close()
        except:
            pass

