"""Celery задачи для OCR обработки"""
from __future__ import annotations

import gc
import json
import logging
import shutil
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict

from .celery_app import celery_app
from .settings import settings
from .storage import (
    Job,
    get_job,
    is_job_paused,
    update_job_status,
    get_node_pdf_r2_key,
    register_ocr_results_to_node,
)
from .rate_limiter import get_datalab_limiter, get_global_ocr_semaphore
from .worker_prompts import (
    fill_image_prompt_variables,
    inject_pdfplumber_to_ocr_text,
    build_strip_prompt,
    parse_batch_response_by_index,
)
from .worker_pdf import extract_pdfplumber_text_for_block, clear_page_size_cache
from .memory_utils import log_memory, log_memory_delta, force_gc, log_pil_images_summary
from .pdf_streaming_v2 import pass1_prepare_crops, pass2_ocr_from_manifest, cleanup_manifest_files
from .task_helpers import check_paused, download_job_files, create_empty_result
from .task_upload import upload_results_to_r2, copy_crops_to_final

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="run_ocr_task", max_retries=3, rate_limit="4/m")
def run_ocr_task(self, job_id: str) -> dict:
    """Celery задача для обработки OCR"""
    start_mem = log_memory(f"[START] Задача {job_id}")
    
    work_dir = None
    try:
        # Получаем задачу из БД с настройками
        job = get_job(job_id, with_files=True, with_settings=True)
        if not job:
            logger.error(f"Задача {job_id} не найдена")
            return {"status": "error", "message": "Job not found"}
        
        if check_paused(job.id):
            return {"status": "paused"}
        
        # Обновляем статус на processing
        update_job_status(job.id, "processing", progress=0.05)
        
        # Создаём временную директорию
        work_dir = Path(tempfile.mkdtemp(prefix=f"ocr_job_{job.id}_"))
        crops_dir = work_dir / "crops"
        crops_dir.mkdir(exist_ok=True)
        
        logger.info(f"Задача {job.id}: скачивание файлов из R2...")
        pdf_path, blocks_path = download_job_files(job, work_dir)
        log_memory_delta("После скачивания файлов", start_mem)
        
        with open(blocks_path, "r", encoding="utf-8") as f:
            blocks_data = json.load(f)
        
        if not blocks_data:
            update_job_status(job.id, "done", progress=1.0)
            create_empty_result(job, work_dir, pdf_path)
            upload_results_to_r2(job, work_dir)
            return {"status": "done", "job_id": job_id}
        
        from rd_core.models import Block
        from rd_core.ocr import create_ocr_engine
        
        blocks = [Block.from_dict(b) for b in blocks_data]
        total_blocks = len(blocks)
        
        logger.info(f"Задача {job.id}: {total_blocks} блоков")
        
        if check_paused(job.id):
            return {"status": "paused"}
        
        update_job_status(job.id, "processing", progress=0.1)
        
        # Настройки из Supabase
        job_settings = job.settings
        text_model = (job_settings.text_model if job_settings else "") or ""
        table_model = (job_settings.table_model if job_settings else "") or ""
        image_model = (job_settings.image_model if job_settings else "") or ""
        
        engine = job.engine or "openrouter"
        datalab_limiter = get_datalab_limiter() if engine == "datalab" else None
        
        if engine == "datalab" and settings.datalab_api_key:
            strip_backend = create_ocr_engine("datalab", api_key=settings.datalab_api_key, rate_limiter=datalab_limiter)
        elif settings.openrouter_api_key:
            strip_model = text_model or table_model or "qwen/qwen3-vl-30b-a3b-instruct"
            strip_backend = create_ocr_engine("openrouter", api_key=settings.openrouter_api_key, model_name=strip_model)
        else:
            strip_backend = create_ocr_engine("dummy")
        
        if settings.openrouter_api_key:
            img_model = image_model or text_model or table_model or "qwen/qwen3-vl-30b-a3b-instruct"
            logger.info(f"IMAGE модель: {img_model}")
            image_backend = create_ocr_engine("openrouter", api_key=settings.openrouter_api_key, model_name=img_model)
        else:
            image_backend = create_ocr_engine("dummy")
        
        # Выбор алгоритма обработки
        if settings.use_two_pass_ocr:
            _run_two_pass_ocr(
                job, pdf_path, blocks, crops_dir, work_dir,
                strip_backend, image_backend, start_mem
            )
        else:
            _run_legacy_ocr(
                job, pdf_path, blocks, crops_dir,
                strip_backend, image_backend, start_mem
            )
        
        force_gc("после OCR обработки")
        
        # Генерация результатов
        r2_prefix = _generate_results(job, pdf_path, blocks, work_dir)
        
        # Загрузка результатов в R2
        logger.info(f"Загрузка результатов в R2...")
        upload_results_to_r2(job, work_dir, r2_prefix)
        
        # Регистрация OCR результатов в node_files
        if job.node_id:
            register_ocr_results_to_node(job.node_id, job.document_name, work_dir)
        
        update_job_status(job.id, "done", progress=1.0)
        logger.info(f"Задача {job.id} завершена успешно")
        
        return {"status": "done", "job_id": job_id}
        
    except Exception as e:
        error_msg = f"{e}\n{traceback.format_exc()}"
        logger.error(f"Ошибка обработки задачи {job_id}: {error_msg}")
        update_job_status(job_id, "error", error_message=str(e))
        return {"status": "error", "message": str(e)}
    
    finally:
        # Очистка временной директории
        if work_dir and work_dir.exists():
            try:
                shutil.rmtree(work_dir)
                logger.info(f"✅ Временная директория очищена: {work_dir}")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка очистки временной директории: {e}")
        
        # Очищаем кэш размеров страниц
        clear_page_size_cache()
        
        # Финальная сборка мусора
        force_gc("финальная")
        log_memory_delta(f"[END] Задача {job_id}", start_mem)


def _run_two_pass_ocr(
    job: Job,
    pdf_path: Path,
    blocks: list,
    crops_dir: Path,
    work_dir: Path,
    strip_backend,
    image_backend,
    start_mem: float,
):
    """Двухпроходный алгоритм OCR (экономия памяти)"""
    logger.info(f"Используется двухпроходный алгоритм (OCR потоков: {settings.ocr_threads_per_job})")
    manifest = None
    
    try:
        # PASS 1: Подготовка кропов на диск
        def on_pass1_progress(current, total):
            progress = 0.1 + 0.3 * (current / total)
            if not is_job_paused(job.id):
                update_job_status(job.id, "processing", progress=progress)
        
        manifest = pass1_prepare_crops(
            str(pdf_path),
            blocks,
            str(crops_dir),
            save_image_crops_as_pdf=True,
            on_progress=on_pass1_progress,
        )
        
        log_memory_delta("После PASS1", start_mem)
        
        if check_paused(job.id):
            return
        
        # PASS 2: OCR с загрузкой с диска
        def on_pass2_progress(current, total):
            progress = 0.4 + 0.5 * (current / total)
            if not is_job_paused(job.id):
                update_job_status(job.id, "processing", progress=progress)
        
        pass2_ocr_from_manifest(
            manifest,
            blocks,
            strip_backend,
            image_backend,
            str(pdf_path),
            on_progress=on_pass2_progress,
            check_paused=lambda: is_job_paused(job.id),
        )
        
        log_memory_delta("После PASS2", start_mem)
        
        # Копируем PDF кропы в crops_final
        copy_crops_to_final(work_dir, blocks)
        
    finally:
        # Очистка временных файлов кропов
        if manifest:
            cleanup_manifest_files(manifest)


def _run_legacy_ocr(
    job: Job,
    pdf_path: Path,
    blocks: list,
    crops_dir: Path,
    strip_backend,
    image_backend,
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
            
            prompt_data = fill_image_prompt_variables(
                prompt_data=block.prompt,
                doc_name=doc_name,
                page_index=block.page_index,
                block_id=block.id,
                hint=getattr(block, 'hint', None),
                pdfplumber_text=pdfplumber_text
            )
            
            global_sem.acquire()
            try:
                text = image_backend.recognize(crop, prompt=prompt_data)
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


def _generate_results(job: Job, pdf_path: Path, blocks: list, work_dir: Path) -> str:
    """Генерация результатов OCR (markdown, annotation)"""
    from rd_core.models import Page, Document, Block, ShapeType
    from rd_core.ocr import generate_structured_json, generate_grouped_result_json
    from .pdf_streaming import get_page_dimensions_streaming
    
    # Логирование состояния блоков
    blocks_with_ocr = sum(1 for b in blocks if b.ocr_text)
    logger.info(f"_generate_results: всего блоков={len(blocks)}, с ocr_text={blocks_with_ocr}")
    for b in blocks[:5]:  # Первые 5 для отладки
        logger.debug(f"  Блок {b.id}: type={b.block_type}, ocr_text={len(b.ocr_text) if b.ocr_text else 'None'}")
    
    # Сохраняем оригинальный порядок блоков (индекс в исходном списке)
    blocks_by_page: dict[int, list[tuple[int, any]]] = {}
    for orig_idx, b in enumerate(blocks):
        blocks_by_page.setdefault(b.page_index, []).append((orig_idx, b))
    
    # Streaming получение размеров страниц
    page_dims = get_page_dimensions_streaming(str(pdf_path))
    
    pages = []
    for page_idx in sorted(blocks_by_page.keys()):
        dims = page_dims.get(page_idx)
        width, height = dims if dims else (0, 0)
        # Сортируем по оригинальному индексу (порядок 1,2,3... как в GUI)
        page_blocks = [b for _, b in sorted(blocks_by_page[page_idx], key=lambda x: x[0])]
        
        # Пересчитываем coords_px и polygon_points
        if width > 0 and height > 0:
            for block in page_blocks:
                old_x1, old_y1, old_x2, old_y2 = block.coords_px
                old_bbox_w = old_x2 - old_x1 if old_x2 != old_x1 else 1
                old_bbox_h = old_y2 - old_y1 if old_y2 != old_y1 else 1
                
                block.coords_px = Block.norm_to_px(block.coords_norm, width, height)
                
                if block.shape_type == ShapeType.POLYGON and block.polygon_points:
                    new_x1, new_y1, new_x2, new_y2 = block.coords_px
                    new_bbox_w = new_x2 - new_x1 if new_x2 != new_x1 else 1
                    new_bbox_h = new_y2 - new_y1 if new_y2 != new_y1 else 1
                    block.polygon_points = [
                        (
                            int(new_x1 + (px - old_x1) / old_bbox_w * new_bbox_w),
                            int(new_y1 + (py - old_y1) / old_bbox_h * new_bbox_h)
                        )
                        for px, py in block.polygon_points
                    ]
        
        pages.append(Page(page_number=page_idx, width=width, height=height, blocks=page_blocks))
    
    # Вычисляем r2_prefix
    if job.node_id:
        pdf_r2_key = get_node_pdf_r2_key(job.node_id)
        if pdf_r2_key:
            from pathlib import PurePosixPath
            r2_prefix = str(PurePosixPath(pdf_r2_key).parent)
        else:
            r2_prefix = f"tree_docs/{job.node_id}"
    else:
        r2_prefix = job.r2_prefix
    
    # Извлекаем путь для markdown ссылок
    if r2_prefix.startswith("tree_docs/"):
        md_project_name = r2_prefix[len("tree_docs/"):]
    else:
        md_project_name = job.node_id if job.node_id else job.id
    
    result_json_path = work_dir / "result.json"
    generate_structured_json(pages, str(result_json_path), project_name=md_project_name, doc_name=pdf_path.name)
    
    annotation_path = work_dir / "annotation.json"
    doc = Document(pdf_path=pdf_path.name, pages=pages)
    with open(annotation_path, "w", encoding="utf-8") as f:
        json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)
    
    # Генерация grouped_result.json с HTML сгруппированным по BLOCK_ID
    grouped_result_path = work_dir / "grouped_result.json"
    try:
        generate_grouped_result_json(
            str(result_json_path),
            str(annotation_path),
            str(grouped_result_path)
        )
    except Exception as e:
        logger.warning(f"Ошибка генерации grouped_result.json: {e}")
    
    return r2_prefix
