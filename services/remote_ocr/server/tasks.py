"""Celery задачи для OCR обработки"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict

from .celery_app import celery_app
from .settings import settings
from .storage import (
    Job,
    add_job_file,
    get_job,
    get_job_file_by_type,
    is_job_paused,
    update_job_status,
)
from .rate_limiter import get_datalab_limiter
from .worker_prompts import (
    fill_image_prompt_variables,
    inject_pdfplumber_to_ocr_text,
    build_strip_prompt,
    parse_batch_response_by_index,
)
from .worker_pdf import extract_pdfplumber_text_for_block

logger = logging.getLogger(__name__)


def _get_r2_storage():
    """Получить R2 Storage клиент"""
    from rd_core.r2_storage import R2Storage
    return R2Storage()


def _check_paused(job_id: str) -> bool:
    """Проверить, не поставлена ли задача на паузу"""
    if is_job_paused(job_id):
        logger.info(f"Задача {job_id} поставлена на паузу")
        return True
    return False


def _download_job_files(job: Job, work_dir: Path) -> tuple[Path, Path]:
    """Скачать файлы задачи из R2 во временную директорию"""
    r2 = _get_r2_storage()
    
    # PDF
    pdf_file = get_job_file_by_type(job.id, "pdf")
    if not pdf_file:
        raise RuntimeError(f"PDF file not found for job {job.id}")
    
    pdf_path = work_dir / "document.pdf"
    if not r2.download_file(pdf_file.r2_key, str(pdf_path)):
        raise RuntimeError(f"Failed to download PDF from R2: {pdf_file.r2_key}")
    
    # Blocks
    blocks_file = get_job_file_by_type(job.id, "blocks")
    if not blocks_file:
        raise RuntimeError(f"Blocks file not found for job {job.id}")
    
    blocks_path = work_dir / "blocks.json"
    if not r2.download_file(blocks_file.r2_key, str(blocks_path)):
        raise RuntimeError(f"Failed to download blocks from R2: {blocks_file.r2_key}")
    
    return pdf_path, blocks_path


def _upload_results_to_r2(job: Job, work_dir: Path) -> str:
    """Загрузить результаты в R2 и записать в БД"""
    r2 = _get_r2_storage()
    r2_prefix = job.r2_prefix
    
    # result.md
    result_md_path = work_dir / "result.md"
    if result_md_path.exists():
        r2_key = f"{r2_prefix}/result.md"
        r2.upload_file(str(result_md_path), r2_key)
        add_job_file(job.id, "result_md", r2_key, "result.md", result_md_path.stat().st_size)
    
    # annotation.json
    annotation_path = work_dir / "annotation.json"
    if annotation_path.exists():
        r2_key = f"{r2_prefix}/annotation.json"
        r2.upload_file(str(annotation_path), r2_key)
        add_job_file(job.id, "annotation", r2_key, "annotation.json", annotation_path.stat().st_size)
    
    # result.zip
    result_zip_path = work_dir / "result.zip"
    if result_zip_path.exists():
        r2_key = f"{r2_prefix}/result.zip"
        r2.upload_file(str(result_zip_path), r2_key)
        add_job_file(job.id, "result_zip", r2_key, "result.zip", result_zip_path.stat().st_size)
    
    # crops/
    crops_dir = work_dir / "crops"
    if crops_dir.exists():
        for crop_file in crops_dir.iterdir():
            if crop_file.is_file() and crop_file.suffix.lower() == ".pdf":
                r2_key = f"{r2_prefix}/crops/{crop_file.name}"
                r2.upload_file(str(crop_file), r2_key)
                add_job_file(job.id, "crop", r2_key, crop_file.name, crop_file.stat().st_size)
    
    return r2_prefix


def _create_empty_result(job: Job, work_dir: Path, pdf_path: Path) -> None:
    """Создать пустой результат"""
    result_md_path = work_dir / "result.md"
    annotation_path = work_dir / "annotation.json"
    result_zip_path = work_dir / "result.zip"
    
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


@celery_app.task(bind=True, name="run_ocr_task", max_retries=3)
def run_ocr_task(self, job_id: str) -> dict:
    """Celery задача для обработки OCR"""
    logger.info(f"[CELERY] Начало обработки задачи {job_id}")
    
    work_dir = None
    try:
        # Получаем задачу из БД с настройками
        job = get_job(job_id, with_files=True, with_settings=True)
        if not job:
            logger.error(f"Задача {job_id} не найдена")
            return {"status": "error", "message": "Job not found"}
        
        if _check_paused(job.id):
            return {"status": "paused"}
        
        # Обновляем статус на processing
        update_job_status(job.id, "processing", progress=0.05)
        
        # Создаём временную директорию
        work_dir = Path(tempfile.mkdtemp(prefix=f"ocr_job_{job.id}_"))
        crops_dir = work_dir / "crops"
        crops_dir.mkdir(exist_ok=True)
        
        logger.info(f"Задача {job.id}: скачивание файлов из R2...")
        pdf_path, blocks_path = _download_job_files(job, work_dir)
        
        with open(blocks_path, "r", encoding="utf-8") as f:
            blocks_data = json.load(f)
        
        if not blocks_data:
            update_job_status(job.id, "done", progress=1.0)
            _create_empty_result(job, work_dir, pdf_path)
            _upload_results_to_r2(job, work_dir)
            return {"status": "done", "job_id": job_id}
        
        from rd_core.models import Block
        from rd_core.cropping import crop_and_merge_blocks_from_pdf
        from rd_core.ocr import create_ocr_engine
        
        blocks = [Block.from_dict(b) for b in blocks_data]
        total_blocks = len(blocks)
        
        logger.info(f"Задача {job.id}: {total_blocks} блоков")
        
        if _check_paused(job.id):
            return {"status": "paused"}
        
        update_job_status(job.id, "processing", progress=0.1)
        strip_paths, strip_images, strips, image_blocks, image_pdf_paths = crop_and_merge_blocks_from_pdf(
            str(pdf_path), blocks, str(crops_dir), save_image_crops_as_pdf=True
        )
        
        logger.info(f"Создано {len(strips)} полос TEXT/TABLE, {len(image_blocks)} IMAGE блоков")
        
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
        
        total_requests = len(strips) + len(image_blocks)
        processed = 0
        
        def _update_progress():
            nonlocal processed
            processed += 1
            if total_requests > 0:
                progress = 0.1 + 0.8 * (processed / total_requests)
                if not is_job_paused(job.id):
                    update_job_status(job.id, "processing", progress=progress)
        
        def _process_strip(strip_idx: int, strip):
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
        
        for block_id, parts_dict in text_block_parts.items():
            block = text_block_objects[block_id]
            total_parts = text_block_total_parts[block_id]
            
            if total_parts == 1:
                block.ocr_text = parts_dict.get(0, "")
            else:
                combined_parts = [parts_dict.get(i, "") for i in range(total_parts)]
                block.ocr_text = "\n\n".join(combined_parts)
        
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
        
        result_md_path = work_dir / "result.md"
        generate_structured_markdown(pages, str(result_md_path), project_name=job.id, doc_name=pdf_path.name)
        
        annotation_path = work_dir / "annotation.json"
        doc = Document(pdf_path=pdf_path.name, pages=pages)
        with open(annotation_path, "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)
        
        result_zip_path = work_dir / "result.zip"
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
        
        # Загрузка результатов в R2
        logger.info(f"Загрузка результатов в R2...")
        _upload_results_to_r2(job, work_dir)
        
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

