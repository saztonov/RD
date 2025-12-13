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
        
        # Создаём OCR движок в зависимости от настроек задачи
        engine = job.engine or "openrouter"
        
        if engine == "datalab" and os.getenv("DATALAB_API_KEY"):
            ocr_backend = create_ocr_engine("datalab", api_key=os.getenv("DATALAB_API_KEY"))
        elif engine == "openrouter" and settings.openrouter_api_key:
            ocr_backend = create_ocr_engine("openrouter", api_key=settings.openrouter_api_key)
        else:
            # Fallback на openrouter или dummy
            if settings.openrouter_api_key:
                ocr_backend = create_ocr_engine("openrouter", api_key=settings.openrouter_api_key)
            else:
                ocr_backend = create_ocr_engine("dummy")
        
        # Запускаем OCR через rd_core с обновлением прогресса
        def _on_progress(done: int, total: int) -> None:
            if total <= 0:
                update_job_status(job.id, "processing", progress=0.9)
                return
            progress = 0.1 + 0.8 * (done / total)
            update_job_status(job.id, "processing", progress=progress)

        run_ocr_for_blocks(blocks, ocr_backend, on_progress=_on_progress)
        
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
        
        # Собираем страницы и аннотацию (Document) + markdown через rd_core
        from rd_core.models import Page, Document  # noqa: E402
        from rd_core.pdf_utils import PDFDocument  # noqa: E402
        from rd_core.ocr import generate_structured_markdown  # noqa: E402

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

        # Формируем markdown
        result_md_path = job_dir / "result.md"
        generate_structured_markdown(pages, str(result_md_path), project_name=job.id)
        
        # Сохраняем полную аннотацию
        annotation_path = job_dir / "annotation.json"
        doc = Document(pdf_path=pdf_path.name, pages=pages)
        with open(annotation_path, "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Создаём zip со всеми результатами
        result_zip_path = job_dir / "result.zip"
        with zipfile.ZipFile(result_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Результаты OCR
            zf.write(result_json_path, "result.json")
            zf.write(result_md_path, "result.md")
            
            # Аннотация
            if annotation_path.exists():
                zf.write(annotation_path, "annotation.json")
            
            # Исходный PDF
            if pdf_path.exists():
                zf.write(pdf_path, "document.pdf")
            
            # Кропы изображений
            if crops_dir.exists():
                for crop_file in crops_dir.iterdir():
                    if crop_file.is_file():
                        zf.write(crop_file, f"crops/{crop_file.name}")
        
        # Загружаем результаты в R2
        r2_prefix = None
        logger.info("=" * 60)
        logger.info("=== НАЧАЛО ЗАГРУЗКИ РЕЗУЛЬТАТОВ В R2 ===")
        logger.info(f"Job ID: {job.id}")
        logger.info(f"Job dir: {job_dir}")
        
        try:
            logger.info("Импорт R2Storage...")
            from rd_core.r2_storage import R2Storage
            
            logger.info("Создание экземпляра R2Storage...")
            r2 = R2Storage()
            logger.info("✅ R2Storage инициализирован")
            
            # Формируем префикс: ocr_results/job_id
            r2_prefix = f"ocr_results/{job.id}"
            logger.info(f"R2 Prefix: {r2_prefix}")
            logger.info(f"Загружаем директорию: {job_dir}")
            
            # Проверяем наличие файлов
            files = list(job_dir.rglob("*"))
            files_to_upload = [f for f in files if f.is_file()]
            logger.info(f"Найдено файлов для загрузки: {len(files_to_upload)}")
            for f in files_to_upload:
                logger.info(f"  - {f.relative_to(job_dir)}")
            
            success, errors = r2.upload_directory(str(job_dir), r2_prefix, recursive=True)
            
            logger.info(f"Результат загрузки: успешно={success}, ошибок={errors}")
            
            if errors == 0:
                logger.info(f"✅ Результаты успешно загружены в R2: {r2_prefix}")
            else:
                logger.warning(f"⚠️ Загрузка в R2 завершена с ошибками: {success} успешно, {errors} ошибок")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки результатов в R2: {type(e).__name__}: {e}", exc_info=True)
            logger.error("Проверьте настройки R2 в .env:")
            logger.error("  - R2_ACCOUNT_ID")
            logger.error("  - R2_ACCESS_KEY_ID")
            logger.error("  - R2_SECRET_ACCESS_KEY")
            logger.error("  - R2_BUCKET_NAME")
            # Не падаем, задача всё равно успешна
        
        logger.info("=== КОНЕЦ ЗАГРУЗКИ РЕЗУЛЬТАТОВ В R2 ===")
        logger.info("=" * 60)
        
        update_job_status(job.id, "done", progress=1.0, result_path=str(result_zip_path), r2_prefix=r2_prefix)
        logger.info(f"Задача {job.id} завершена успешно")
        
        # Очистка файлов с сервера после сохранения в R2
        if r2_prefix:
            try:
                import shutil
                logger.info(f"Очистка файлов задачи {job.id} с сервера...")
                
                # Удаляем все файлы кроме result.zip (для возможности скачивания)
                files_to_remove = [
                    pdf_path,  # document.pdf
                    blocks_path,  # blocks.json
                    result_json_path,  # result.json
                    result_md_path,  # result.md
                    annotation_path,  # annotation.json
                ]
                
                for file_path in files_to_remove:
                    if file_path.exists():
                        file_path.unlink()
                        logger.debug(f"  Удалён: {file_path.name}")
                
                # Удаляем папку с кропами
                if crops_dir.exists():
                    shutil.rmtree(crops_dir)
                    logger.debug(f"  Удалена папка: crops/")
                
                logger.info(f"✅ Файлы задачи {job.id} очищены с сервера (result.zip сохранён)")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка очистки файлов задачи {job.id}: {e}")
        
    except Exception as e:
        error_msg = f"{e}\n{traceback.format_exc()}"
        logger.error(f"Ошибка обработки задачи {job.id}: {error_msg}")
        update_job_status(job.id, "error", error_message=str(e))


def _create_empty_result(job_dir: Path) -> None:
    """Создать пустой результат"""
    result_json_path = job_dir / "result.json"
    result_md_path = job_dir / "result.md"
    annotation_path = job_dir / "annotation.json"
    result_zip_path = job_dir / "result.zip"
    pdf_path = job_dir / "document.pdf"
    
    with open(result_json_path, "w", encoding="utf-8") as f:
        json.dump([], f)
    
    with open(result_md_path, "w", encoding="utf-8") as f:
        f.write("# OCR Results\n\nNo blocks to process.\n")
    
    with open(annotation_path, "w", encoding="utf-8") as f:
        from rd_core.models import Document  # noqa: E402
        json.dump(Document(pdf_path=pdf_path.name, pages=[]).to_dict(), f, ensure_ascii=False, indent=2)
    
    with zipfile.ZipFile(result_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(result_json_path, "result.json")
        zf.write(result_md_path, "result.md")
        zf.write(annotation_path, "annotation.json")
        if pdf_path.exists():
            zf.write(pdf_path, "document.pdf")
