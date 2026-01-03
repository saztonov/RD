"""
Двухпроходный алгоритм OCR с минимальным потреблением памяти.

PASS 1: Подготовка кропов → сохранение на диск
PASS 2: OCR с загрузкой по одному кропу с диска
"""
from __future__ import annotations

import gc
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from .memory_utils import force_gc, log_memory, log_memory_delta
from .pdf_streaming import (
    StreamingPDFProcessor,
    merge_crops_vertically,
    split_large_crop,
)
from .settings import settings
from .manifest_models import CropManifestEntry, StripManifestEntry, TwoPassManifest

# Константы из настроек
MAX_STRIP_HEIGHT = settings.max_strip_height
MAX_SINGLE_BLOCK_HEIGHT = settings.max_strip_height

logger = logging.getLogger(__name__)


def pass1_prepare_crops(
    pdf_path: str,
    blocks: List,
    crops_dir: str,
    padding: int = 5,
    save_image_crops_as_pdf: bool = True,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> TwoPassManifest:
    """
    PASS 1: Вырезать все кропы и сохранить на диск.
    
    Группирует TEXT/TABLE блоки в strips, IMAGE блоки сохраняет отдельно.
    Память освобождается после каждой страницы.
    """
    from rd_core.models import BlockType
    
    os.makedirs(crops_dir, exist_ok=True)
    strips_dir = os.path.join(crops_dir, "strips")
    images_dir = os.path.join(crops_dir, "images")
    os.makedirs(strips_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    
    start_mem = log_memory(f"PASS1 start (PDF: {os.path.getsize(pdf_path) / 1024 / 1024:.1f} MB)")
    
    # Группируем блоки по страницам
    blocks_by_page: Dict[int, List] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page_index, []).append(block)
    
    # Временное хранение путей к кропам
    block_crop_paths: Dict[str, List[Tuple[str, int, int]]] = {}  # block_id -> [(path, part_idx, total_parts)]
    image_block_entries: List[CropManifestEntry] = []
    image_pdf_paths: Dict[str, str] = {}
    
    processed_pages = 0
    total_pages = len(blocks_by_page)
    
    compress_level = settings.crop_png_compress
    
    with StreamingPDFProcessor(pdf_path) as processor:
        logger.info(f"PASS1: {processor.page_count} страниц, {len(blocks)} блоков")
        
        for page_idx in sorted(blocks_by_page.keys()):
            page_blocks = blocks_by_page[page_idx]
            
            for block in page_blocks:
                try:
                    crop = processor.crop_block_image(block, padding)
                    if not crop:
                        continue
                    
                    # Разделяем большие кропы
                    crop_parts = split_large_crop(crop, MAX_SINGLE_BLOCK_HEIGHT)
                    total_parts = len(crop_parts)
                    
                    block_crop_paths[block.id] = []
                    
                    for part_idx, crop_part in enumerate(crop_parts):
                        if block.block_type == BlockType.IMAGE:
                            # IMAGE блоки сохраняем отдельно
                            crop_filename = f"{block.id}_p{part_idx}.png"
                            crop_path = os.path.join(images_dir, crop_filename)
                        else:
                            # TEXT/TABLE — для последующей группировки в strips
                            crop_filename = f"{block.id}_p{part_idx}.png"
                            crop_path = os.path.join(crops_dir, crop_filename)
                        
                        crop_part.save(crop_path, "PNG", compress_level=compress_level)
                        
                        block_crop_paths[block.id].append((crop_path, part_idx, total_parts))
                        
                        if block.block_type == BlockType.IMAGE:
                            image_block_entries.append(CropManifestEntry(
                                block_id=block.id,
                                crop_path=crop_path,
                                block_type=block.block_type.value,
                                page_index=block.page_index,
                                part_idx=part_idx,
                                total_parts=total_parts,
                                width=crop_part.width,
                                height=crop_part.height,
                            ))
                        
                        crop_part.close()
                    
                    # Закрываем оригинальный crop если он отличается от parts
                    if total_parts > 1:
                        crop.close()
                    
                    # PDF кроп для IMAGE блоков
                    if save_image_crops_as_pdf and block.block_type == BlockType.IMAGE:
                        pdf_crop_path = os.path.join(images_dir, f"{block.id}.pdf")
                        result = processor.crop_block_to_pdf(block, pdf_crop_path, padding_pt=2)
                        if result:
                            image_pdf_paths[block.id] = result
                            block.image_file = result
                    
                except Exception as e:
                    logger.error(f"PASS1: ошибка блока {block.id}: {e}")
            
            processed_pages += 1
            if on_progress:
                on_progress(processed_pages, total_pages)
            
            # GC после каждой страницы
            gc.collect()
        
        log_memory_delta("PASS1 после кропов", start_mem)
    
    # Теперь группируем TEXT/TABLE в strips и сохраняем merged images
    strips = _group_and_merge_strips(blocks, block_crop_paths, strips_dir, compress_level)
    
    # Удаляем промежуточные кропы TEXT/TABLE (strips уже сохранены)
    for block in blocks:
        if block.block_type != BlockType.IMAGE and block.id in block_crop_paths:
            for crop_path, _, _ in block_crop_paths[block.id]:
                try:
                    if os.path.exists(crop_path):
                        os.remove(crop_path)
                except:
                    pass
    
    manifest = TwoPassManifest(
        pdf_path=pdf_path,
        crops_dir=crops_dir,
        strips=strips,
        image_blocks=image_block_entries,
        total_blocks=len(blocks),
    )
    
    # Сохраняем manifest
    manifest_path = os.path.join(crops_dir, "manifest.json")
    manifest.save(manifest_path)
    
    force_gc("PASS1 завершён")
    log_memory_delta("PASS1 end", start_mem)
    
    logger.info(f"PASS1 завершён: {len(strips)} strips, {len(image_block_entries)} image crops")
    
    return manifest


def _group_and_merge_strips(
    blocks: List,
    block_crop_paths: Dict[str, List[Tuple[str, int, int]]],
    strips_dir: str,
    compress_level: int,
) -> List[StripManifestEntry]:
    """Группировка TEXT/TABLE блоков в strips и сохранение merged images"""
    from rd_core.models import BlockType
    
    strips: List[StripManifestEntry] = []
    current_strip_blocks: List[Tuple[str, str, int, int]] = []  # (block_id, crop_path, part_idx, total_parts)
    current_strip_height = 0
    strip_counter = 0
    gap = 20
    
    def _save_current_strip():
        nonlocal strip_counter, current_strip_blocks, current_strip_height
        
        if not current_strip_blocks:
            return
        
        strip_counter += 1
        strip_id = f"strip_{strip_counter:04d}"
        strip_path = os.path.join(strips_dir, f"{strip_id}.png")
        
        # Загружаем кропы, объединяем, сохраняем
        crops = []
        for block_id, crop_path, part_idx, total_parts in current_strip_blocks:
            try:
                crop = Image.open(crop_path)
                crops.append(crop)
            except Exception as e:
                logger.error(f"Ошибка загрузки кропа {crop_path}: {e}")
        
        if crops:
            try:
                # Извлекаем block_ids для разделителей
                block_ids = [b[0] for b in current_strip_blocks]
                merged = merge_crops_vertically(crops, gap, block_ids=block_ids)
                merged.save(strip_path, "PNG", compress_level=compress_level)
                merged.close()
            except Exception as e:
                logger.error(f"Ошибка создания strip {strip_id}: {e}")
                strip_path = ""
            finally:
                for c in crops:
                    try:
                        c.close()
                    except:
                        pass
        
        strips.append(StripManifestEntry(
            strip_id=strip_id,
            strip_path=strip_path,
            block_ids=[b[0] for b in current_strip_blocks],
            block_parts=[
                {"block_id": b[0], "part_idx": b[2], "total_parts": b[3]}
                for b in current_strip_blocks
            ],
        ))
        
        current_strip_blocks = []
        current_strip_height = 0
    
    for block in blocks:
        if block.block_type == BlockType.IMAGE:
            # IMAGE блоки не прерывают группировку TEXT блоков
            # Все TEXT блоки группируются в батчи независимо от IMAGE между ними
            continue
        
        if block.id not in block_crop_paths:
            continue
        
        for crop_path, part_idx, total_parts in block_crop_paths[block.id]:
            # Получаем высоту без загрузки полного изображения
            try:
                with Image.open(crop_path) as img:
                    crop_height = img.height
            except:
                crop_height = 500  # fallback
            
            new_height = crop_height + (gap if current_strip_blocks else 0)
            
            if current_strip_height + new_height > MAX_STRIP_HEIGHT and current_strip_blocks:
                _save_current_strip()
                new_height = crop_height
            
            current_strip_blocks.append((block.id, crop_path, part_idx, total_parts))
            current_strip_height += new_height
    
    # Сохраняем последний strip
    _save_current_strip()
    
    return strips


def pass2_ocr_from_manifest(
    manifest: TwoPassManifest,
    blocks: List,
    strip_backend,
    image_backend,
    stamp_backend,
    pdf_path: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    check_paused: Optional[Callable[[], bool]] = None,
) -> None:
    """
    PASS 2: OCR с загрузкой кропов с диска.
    
    Параллельная обработка с ограничением потоков.
    Результаты записываются в block.ocr_text
    """
    from .rate_limiter import get_global_ocr_semaphore
    from .worker_prompts import (
        build_strip_prompt,
        fill_image_prompt_variables,
        inject_pdfplumber_to_ocr_text,
        parse_batch_response_by_index,
    )
    from .worker_pdf import extract_pdfplumber_text_for_block
    
    start_mem = log_memory("PASS2 start")
    
    total_requests = len(manifest.strips) + len(manifest.image_blocks)
    processed = 0
    
    # Создаём индекс блоков по id
    blocks_by_id = {b.id: b for b in blocks}
    
    # Результаты для сборки частей блоков
    text_block_parts: Dict[str, Dict[int, str]] = {}
    text_block_total_parts: Dict[str, int] = {}
    image_block_parts: Dict[str, Dict[int, str]] = {}
    image_block_total_parts: Dict[str, int] = {}
    
    global_sem = get_global_ocr_semaphore(settings.max_global_ocr_requests)
    max_workers = settings.ocr_threads_per_job
    
    def _update_progress():
        nonlocal processed
        processed += 1
        if on_progress and total_requests > 0:
            on_progress(processed, total_requests)
    
    # --- Обработка strips ---
    def _process_strip(strip: StripManifestEntry):
        if check_paused and check_paused():
            return None
        
        if not strip.strip_path or not os.path.exists(strip.strip_path):
            logger.warning(f"Strip {strip.strip_id} не найден: {strip.strip_path}")
            return None
        
        try:
            # Загружаем merged image с диска
            with Image.open(strip.strip_path) as merged_image:
                # Собираем блоки для промпта
                strip_blocks = [blocks_by_id[bp["block_id"]] for bp in strip.block_parts if bp["block_id"] in blocks_by_id]
                
                if not strip_blocks:
                    return None
                
                prompt_data = build_strip_prompt(strip_blocks)
                
                logger.info(f"PASS2: начало обработки strip {strip.strip_id} ({len(strip.block_parts)} блоков)")
                
                global_sem.acquire()
                try:
                    response_text = strip_backend.recognize(merged_image, prompt=prompt_data)
                finally:
                    global_sem.release()
                
                logger.info(f"PASS2: завершена обработка strip {strip.strip_id}")
            
            # Парсим результат
            index_results = parse_batch_response_by_index(len(strip.block_parts), response_text)
            
            return strip, index_results
            
        except Exception as e:
            logger.error(f"PASS2 strip {strip.strip_id}: {e}")
            return None
    
    logger.info(f"PASS2: обработка {len(manifest.strips)} strips ({max_workers} потоков)")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_strip, strip): strip for strip in manifest.strips}
        
        for future in as_completed(futures):
            result = future.result()
            if result:
                strip, index_results = result
                
                for i, bp in enumerate(strip.block_parts):
                    block_id = bp["block_id"]
                    part_idx = bp["part_idx"]
                    total_parts = bp["total_parts"]
                    text = index_results.get(i, "")
                    
                    if block_id not in text_block_parts:
                        text_block_parts[block_id] = {}
                        text_block_total_parts[block_id] = total_parts
                    
                    text_block_parts[block_id][part_idx] = text
            
            _update_progress()
            gc.collect()
    
    # Собираем части TEXT/TABLE блоков
    for block_id, parts_dict in text_block_parts.items():
        if block_id not in blocks_by_id:
            continue
        block = blocks_by_id[block_id]
        total_parts = text_block_total_parts.get(block_id, 1)
        
        if total_parts == 1:
            block.ocr_text = parts_dict.get(0, "")
        else:
            combined = [parts_dict.get(i, "") for i in range(total_parts)]
            block.ocr_text = "\n\n".join(combined)
        logger.info(f"PASS2 TEXT блок {block_id}: ocr_text длина = {len(block.ocr_text) if block.ocr_text else 0}")
    
    log_memory_delta("PASS2 после strips", start_mem)
    
    # --- Обработка IMAGE блоков ---
    def _process_image(entry: CropManifestEntry):
        if check_paused and check_paused():
            return None
        
        if not os.path.exists(entry.crop_path):
            logger.warning(f"Image crop не найден: {entry.crop_path}")
            return None
        
        block = blocks_by_id.get(entry.block_id)
        if not block:
            return None
        
        try:
            with Image.open(entry.crop_path) as crop:
                pdfplumber_text = extract_pdfplumber_text_for_block(
                    pdf_path, block.page_index, block.coords_norm
                )
                
                # Получаем category_id и category_code из блока
                category_id = getattr(block, 'category_id', None)
                category_code = getattr(block, 'category_code', None)
                
                prompt_data = fill_image_prompt_variables(
                    prompt_data=block.prompt,
                    doc_name=Path(pdf_path).name,
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
                
                logger.info(f"PASS2: начало обработки IMAGE блока {entry.block_id}")
                
                global_sem.acquire()
                try:
                    text = backend.recognize(crop, prompt=prompt_data)
                finally:
                    global_sem.release()
                
                logger.info(f"PASS2: завершена обработка IMAGE блока {entry.block_id}")
                
                text = inject_pdfplumber_to_ocr_text(text, pdfplumber_text)
                block.pdfplumber_text = pdfplumber_text
            
            return entry.block_id, text, entry.part_idx, entry.total_parts
            
        except Exception as e:
            logger.error(f"PASS2 image {entry.block_id}: {e}")
            return entry.block_id, f"[Ошибка: {e}]", entry.part_idx, entry.total_parts
    
    logger.info(f"PASS2: обработка {len(manifest.image_blocks)} image blocks")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_image, entry): entry for entry in manifest.image_blocks}
        
        for future in as_completed(futures):
            result = future.result()
            if result:
                block_id, text, part_idx, total_parts = result
                
                if block_id not in image_block_parts:
                    image_block_parts[block_id] = {}
                    image_block_total_parts[block_id] = total_parts
                
                image_block_parts[block_id][part_idx] = text
            
            _update_progress()
            gc.collect()
    
    # Собираем части IMAGE блоков
    for block_id, parts_dict in image_block_parts.items():
        if block_id not in blocks_by_id:
            continue
        block = blocks_by_id[block_id]
        total_parts = image_block_total_parts.get(block_id, 1)
        
        if total_parts == 1:
            block.ocr_text = parts_dict.get(0, "")
        else:
            combined = [parts_dict.get(i, "") for i in range(total_parts)]
            block.ocr_text = "\n\n".join(combined)
        logger.info(f"PASS2 IMAGE блок {block_id}: ocr_text длина = {len(block.ocr_text) if block.ocr_text else 0}")
    
    force_gc("PASS2 завершён")
    log_memory_delta("PASS2 end", start_mem)
    
    logger.info(f"PASS2 завершён: {processed} запросов обработано")


def cleanup_manifest_files(manifest: TwoPassManifest) -> None:
    """Удалить все временные файлы после обработки"""
    try:
        crops_dir = manifest.crops_dir
        if os.path.exists(crops_dir):
            shutil.rmtree(crops_dir)
            logger.info(f"Удалена директория кропов: {crops_dir}")
    except Exception as e:
        logger.warning(f"Ошибка удаления кропов: {e}")
