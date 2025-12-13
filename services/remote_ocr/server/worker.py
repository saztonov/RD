"""Фоновый воркер для обработки OCR задач"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Optional

from .storage import Job, claim_next_job, update_job_status
from .settings import settings

logger = logging.getLogger(__name__)

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def start_worker() -> None:
    """Запустить фоновый воркер"""
    global _worker_thread
    
    if _worker_thread is not None and _worker_thread.is_alive():
        logger.warning("Worker уже запущен")
        return
    
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
    """Главный цикл воркера"""
    while not _stop_event.is_set():
        try:
            job = claim_next_job()
            if job:
                logger.info(f"Взята задача {job.id}")
                _process_job(job)
            else:
                time.sleep(2.0)
        except Exception as e:
            logger.error(f"Ошибка в worker loop: {e}")
            time.sleep(5.0)


def _process_job(job: Job) -> None:
    """Обработать одну задачу OCR"""
    try:
        job_dir = Path(job.job_dir)
        pdf_path = job_dir / "document.pdf"
        blocks_path = job_dir / "blocks.json"
        crops_dir = job_dir / "crops"
        crops_dir.mkdir(exist_ok=True)
        
        # Загружаем блоки
        with open(blocks_path, "r", encoding="utf-8") as f:
            blocks_data = json.load(f)
        
        if not blocks_data:
            update_job_status(job.id, "done", progress=1.0, result_path=str(job_dir / "result.zip"))
            _create_empty_result(job_dir)
            return
        
        # Импортируем rd_core
        from rd_core.models import Block
        from rd_core.cropping import crop_blocks_from_pdf
        from rd_core.ocr import create_ocr_engine, run_ocr_for_blocks
        
        # Восстанавливаем блоки
        blocks = [Block.from_dict(b) for b in blocks_data]
        total_blocks = len(blocks)
        
        logger.info(f"Задача {job.id}: {total_blocks} блоков")
        
        # Вырезаем кропы
        update_job_status(job.id, "processing", progress=0.1)
        crop_results = crop_blocks_from_pdf(str(pdf_path), blocks, str(crops_dir))
        
        # Обновляем image_file в блоках
        crop_map = {block.id: path for block, path in crop_results}
        for block in blocks:
            if block.id in crop_map:
                block.image_file = crop_map[block.id]
        
        # Создаём OCR движок
        if settings.openrouter_api_key:
            ocr_backend = create_ocr_engine("openrouter", api_key=settings.openrouter_api_key)
        else:
            ocr_backend = create_ocr_engine("dummy")
        
        # Запускаем OCR с обновлением прогресса
        for i, block in enumerate(blocks):
            if block.image_file and os.path.exists(block.image_file):
                try:
                    from PIL import Image
                    img = Image.open(block.image_file)
                    result = ocr_backend.recognize(img)
                    block.ocr_text = result
                except Exception as e:
                    logger.error(f"OCR error для блока {block.id}: {e}")
                    block.ocr_text = f"[OCR error: {e}]"
            
            progress = 0.1 + 0.8 * ((i + 1) / total_blocks)
            update_job_status(job.id, "processing", progress=progress)
        
        # Формируем результаты
        result_json = [
            {
                "block_id": block.id,
                "text": block.ocr_text or "",
                "type": block.block_type.value,
                "page_index": block.page_index,
                "category": block.category
            }
            for block in blocks
        ]
        
        result_json_path = job_dir / "result.json"
        with open(result_json_path, "w", encoding="utf-8") as f:
            json.dump(result_json, f, ensure_ascii=False, indent=2)
        
        # Формируем markdown
        result_md_path = job_dir / "result.md"
        _generate_result_md(blocks, result_md_path)
        
        # Создаём zip
        result_zip_path = job_dir / "result.zip"
        with zipfile.ZipFile(result_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(result_json_path, "result.json")
            zf.write(result_md_path, "result.md")
        
        update_job_status(job.id, "done", progress=1.0, result_path=str(result_zip_path))
        logger.info(f"Задача {job.id} завершена успешно")
        
    except Exception as e:
        error_msg = f"{e}\n{traceback.format_exc()}"
        logger.error(f"Ошибка обработки задачи {job.id}: {error_msg}")
        update_job_status(job.id, "error", error_message=str(e))


def _generate_result_md(blocks, output_path: Path) -> None:
    """Сгенерировать markdown из результатов OCR"""
    parts = ["# OCR Results\n\n"]
    
    for block in blocks:
        if block.ocr_text:
            category = f"**{block.category}**\n\n" if block.category else ""
            block_type = block.block_type.value.upper()
            parts.append(f"## {block_type} (page {block.page_index + 1})\n\n")
            parts.append(category)
            parts.append(f"{block.ocr_text}\n\n---\n\n")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))


def _create_empty_result(job_dir: Path) -> None:
    """Создать пустой результат"""
    result_json_path = job_dir / "result.json"
    result_md_path = job_dir / "result.md"
    result_zip_path = job_dir / "result.zip"
    
    with open(result_json_path, "w", encoding="utf-8") as f:
        json.dump([], f)
    
    with open(result_md_path, "w", encoding="utf-8") as f:
        f.write("# OCR Results\n\nNo blocks to process.\n")
    
    with zipfile.ZipFile(result_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(result_json_path, "result.json")
        zf.write(result_md_path, "result.md")
