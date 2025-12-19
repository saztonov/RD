"""Фоновый воркер для обработки OCR задач"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Dict

from .storage import Job, claim_next_job, update_job_status, recover_stuck_jobs
from .settings import settings
from .rate_limiter import get_datalab_limiter
from .worker_prompts import (
    fill_image_prompt_variables,
    inject_pdfplumber_to_ocr_text,
    build_strip_prompt,
    parse_batch_response_by_index
)
from .worker_pdf import extract_pdfplumber_text_for_block

# Настройка логирования для воркера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def start_worker() -> None:
    """Запустить фоновый воркер"""
    global _worker_thread
    
    if _worker_thread is not None and _worker_thread.is_alive():
        logger.warning("Worker уже запущен")
        return
    
    recovered = recover_stuck_jobs()
    if recovered > 0:
        print(f"[WORKER] Восстановлено {recovered} застрявших задач", flush=True)
    
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="ocr-worker")
    _worker_thread.start()
    logger.info("OCR Worker запущен")


def stop_worker() -> None:
    """Остановить воркер"""
    global _worker_thread
    _stop_event.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=5.0)
        _worker_thread = None
    logger.info("OCR Worker остановлен")


def _worker_loop() -> None:
    """Главный цикл воркера с параллельной обработкой задач"""
    max_jobs = settings.max_concurrent_jobs
    job_executor = ThreadPoolExecutor(max_workers=max_jobs, thread_name_prefix="job-worker")
    active_futures = set()
    
    logger.info(f"Worker запущен с лимитом {max_jobs} параллельных задач")
    
    while not _stop_event.is_set():
        try:
            # Убираем завершённые задачи
            done_futures = {f for f in active_futures if f.done()}
            for f in done_futures:
                try:
                    f.result()  # Получаем исключения если были
                except Exception as e:
                    logger.error(f"Ошибка в задаче: {e}")
            active_futures -= done_futures
            
            # Берём новую задачу если есть слоты
            if len(active_futures) < max_jobs:
                job = claim_next_job(max_concurrent=max_jobs)
                if job:
                    logger.info(f"Взята задача {job.id} (активных: {len(active_futures) + 1}/{max_jobs})")
                    future = job_executor.submit(_process_job, job)
                    active_futures.add(future)
                else:
                    time.sleep(2.0)
            else:
                time.sleep(1.0)
        except Exception as e:
            logger.error(f"Ошибка в worker loop: {e}")
            time.sleep(5.0)
    
    # Ожидаем завершения активных задач
    job_executor.shutdown(wait=True)


def _process_job(job: Job) -> None:
    """Обработать одну задачу OCR"""
    try:
        job_dir = Path(job.job_dir)
        pdf_path = job_dir / "document.pdf"
        blocks_path = job_dir / "blocks.json"
        job_settings_path = job_dir / "job_settings.json"
        crops_dir = job_dir / "crops"
        crops_dir.mkdir(exist_ok=True)
        
        with open(blocks_path, "r", encoding="utf-8") as f:
            blocks_data = json.load(f)
        
        if not blocks_data:
            update_job_status(job.id, "done", progress=1.0, result_path=str(job_dir / "result.zip"))
            _create_empty_result(job_dir)
            return
        
        from rd_core.models import Block
        from rd_core.cropping import crop_and_merge_blocks_from_pdf
        from rd_core.ocr import create_ocr_engine
        
        blocks = [Block.from_dict(b) for b in blocks_data]
        total_blocks = len(blocks)
        
        logger.info(f"Задача {job.id}: {total_blocks} блоков")
        
        update_job_status(job.id, "processing", progress=0.1)
        strip_paths, strip_images, strips, image_blocks, image_pdf_paths = crop_and_merge_blocks_from_pdf(
            str(pdf_path), blocks, str(crops_dir), save_image_crops_as_pdf=True
        )
        
        logger.info(f"Создано {len(strips)} полос TEXT/TABLE, {len(image_blocks)} IMAGE блоков")
        
        # Загружаем настройки задачи
        job_settings = {}
        if job_settings_path.exists():
            try:
                with open(job_settings_path, "r", encoding="utf-8") as f:
                    job_settings = json.load(f) or {}
            except Exception:
                job_settings = {}

        text_model = (job_settings.get("text_model") or "").strip()
        table_model = (job_settings.get("table_model") or "").strip()
        image_model = (job_settings.get("image_model") or "").strip()

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
            logger.info(f"IMAGE модель: {img_model} (из job_settings.image_model={image_model!r})")
            image_backend = create_ocr_engine("openrouter", api_key=settings.openrouter_api_key, model_name=img_model)
        else:
            image_backend = create_ocr_engine("dummy")
        
        total_requests = len(strips) + len(image_blocks)
        processed = 0
        progress_lock = threading.Lock()
        
        def _update_progress():
            nonlocal processed
            with progress_lock:
                processed += 1
                if total_requests > 0:
                    progress = 0.1 + 0.8 * (processed / total_requests)
                    update_job_status(job.id, "processing", progress=progress)
        
        def _process_strip(strip_idx: int, strip):
            """Обработать одну полосу TEXT/TABLE блоков"""
            try:
                logger.info(f"Обработка полосы {strip_idx + 1}/{len(strips)}: {len(strip.blocks)} блоков")
                merged_image = strip_images.get(strip.strip_id)
                if not merged_image:
                    return {}, []
                
                prompt_data = build_strip_prompt(strip.blocks)
                
                try:
                    response_text = strip_backend.recognize(merged_image, prompt=prompt_data)
                except Exception as ocr_err:
                    logger.error(f"Ошибка OCR для полосы {strip_idx + 1}: {ocr_err}")
                    response_text = None
                
                index_results = parse_batch_response_by_index(len(strip.blocks), response_text)
                return index_results, strip.block_parts
                
            except Exception as e:
                logger.error(f"Ошибка обработки полосы {strip_idx + 1}: {e}", exc_info=True)
                return {}, []
        
        def _process_image_block(img_idx: int, block, crop, part_idx: int, total_parts: int):
            """Обработать один IMAGE блок"""
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
                
                text = image_backend.recognize(crop, prompt=prompt_data)
                text = inject_pdfplumber_to_ocr_text(text, pdfplumber_text)
                
                # Сохраняем pdfplumber_text в блоке для последующей генерации markdown
                block.pdfplumber_text = pdfplumber_text
                
                return block.id, text, part_idx, total_parts
                
            except Exception as e:
                logger.error(f"Ошибка OCR для IMAGE блока {block.id}: {e}")
                return block.id, f"[Ошибка: {e}]", part_idx, total_parts
        
        max_workers = settings.datalab_max_concurrent if engine == "datalab" else 5
        
        text_block_parts: Dict[str, Dict[int, str]] = {}
        text_block_total_parts: Dict[str, int] = {}
        text_block_objects: Dict[str, object] = {}
        
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
                                seen_blocks.add(block.id)
                except Exception as e:
                    logger.error(f"Ошибка получения результата полосы: {e}")
                finally:
                    _update_progress()
        
        # Объединяем результаты частей TEXT/TABLE
        for block_id, parts_dict in text_block_parts.items():
            block = text_block_objects[block_id]
            total_parts = text_block_total_parts[block_id]
            
            if total_parts == 1:
                block.ocr_text = parts_dict.get(0, "")
            else:
                combined_parts = [parts_dict.get(i, "") for i in range(total_parts)]
                block.ocr_text = "\n\n".join(combined_parts)
        
        # IMAGE блоки
        block_parts_results: Dict[str, Dict[int, str]] = {}
        block_total_parts: Dict[str, int] = {}
        block_objects: Dict[str, object] = {}
        
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
        
        # Объединяем результаты IMAGE
        for block_id, parts_dict in block_parts_results.items():
            block = block_objects[block_id]
            total_parts = block_total_parts[block_id]
            
            if total_parts == 1:
                block.ocr_text = parts_dict.get(0, "")
            else:
                combined_parts = [parts_dict.get(i, "") for i in range(total_parts)]
                block.ocr_text = "\n\n".join(combined_parts)
        
        logger.info(f"OCR завершён: {processed} запросов обработано")
        
        # Генерация результатов
        from rd_core.models import Page, Document
        from rd_core.pdf_utils import PDFDocument
        from rd_core.ocr import generate_structured_markdown

        blocks_by_page: dict[int, list] = {}
        for b in blocks:
            blocks_by_page.setdefault(b.page_index, []).append(b)

        pages = []
        with PDFDocument(str(pdf_path)) as pdf:
            for page_idx in sorted(blocks_by_page.keys()):
                dims = pdf.get_page_dimensions(page_idx)
                width, height = dims if dims else (0, 0)
                page_blocks = sorted(blocks_by_page[page_idx], key=lambda bl: bl.coords_px[1])
                pages.append(Page(page_number=page_idx, width=width, height=height, blocks=page_blocks))

        result_md_path = job_dir / "result.md"
        generate_structured_markdown(pages, str(result_md_path), project_name=job.id, doc_name=pdf_path.name)
        
        annotation_path = job_dir / "annotation.json"
        doc = Document(pdf_path=pdf_path.name, pages=pages)
        with open(annotation_path, "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)
        
        result_zip_path = job_dir / "result.zip"
        with zipfile.ZipFile(result_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(result_md_path, "result.md")
            if annotation_path.exists():
                zf.write(annotation_path, "annotation.json")
            if pdf_path.exists():
                zf.write(pdf_path, "document.pdf")
            if crops_dir.exists():
                for crop_file in crops_dir.iterdir():
                    if crop_file.is_file() and crop_file.suffix.lower() == ".pdf":
                        zf.write(crop_file, f"crops/{crop_file.name}")
        
        # Загрузка в R2
        r2_prefix = None
        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
            r2_prefix = f"ocr_results/{job.id}"
            success, errors = r2.upload_directory(str(job_dir), r2_prefix, recursive=True)
            
            if errors == 0:
                logger.info(f"✅ Результаты загружены в R2: {r2_prefix}")
            else:
                logger.warning(f"⚠️ Загрузка в R2: {success} успешно, {errors} ошибок")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки в R2: {e}")
        
        update_job_status(job.id, "done", progress=1.0, result_path=str(result_zip_path), r2_prefix=r2_prefix)
        logger.info(f"Задача {job.id} завершена успешно")
        
        # Очистка файлов
        if r2_prefix:
            try:
                import shutil
                for file_path in [pdf_path, blocks_path, result_md_path, annotation_path, result_zip_path]:
                    if file_path.exists():
                        file_path.unlink()
                if crops_dir.exists():
                    shutil.rmtree(crops_dir)
                logger.info(f"✅ Файлы задачи {job.id} очищены")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка очистки файлов: {e}")
        
    except Exception as e:
        error_msg = f"{e}\n{traceback.format_exc()}"
        logger.error(f"Ошибка обработки задачи {job.id}: {error_msg}")
        update_job_status(job.id, "error", error_message=str(e))


def _create_empty_result(job_dir: Path) -> None:
    """Создать пустой результат"""
    result_md_path = job_dir / "result.md"
    annotation_path = job_dir / "annotation.json"
    result_zip_path = job_dir / "result.zip"
    pdf_path = job_dir / "document.pdf"
    
    with open(result_md_path, "w", encoding="utf-8") as f:
        f.write("# OCR Results\n\nNo blocks to process.\n")
    
    with open(annotation_path, "w", encoding="utf-8") as f:
        from rd_core.models import Document
        json.dump(Document(pdf_path=pdf_path.name, pages=[]).to_dict(), f, ensure_ascii=False, indent=2)
    
    with zipfile.ZipFile(result_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(result_md_path, "result.md")
        zf.write(annotation_path, "annotation.json")
        if pdf_path.exists():
            zf.write(pdf_path, "document.pdf")
