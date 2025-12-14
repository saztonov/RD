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


def _build_strip_prompt(blocks: list) -> dict:
    """
    Построить промпт для batch запроса (полоса TEXT/TABLE блоков).
    Формат ответа: [1] результат первого ... [N] результат N-го
    """
    if len(blocks) == 1:
        # Один блок - простой промпт
        block = blocks[0]
        if block.prompt:
            return block.prompt
        return {
            "system": "You are an expert OCR system. Extract text accurately.",
            "user": "Распознай текст на изображении. Сохрани форматирование."
        }
    
    # Несколько блоков - batch prompt
    system = "You are an expert OCR system. Extract text from each block accurately."
    user = "Распознай текст на изображении."
    
    batch_instruction = (
        f"\n\nНа изображении {len(blocks)} блоков, расположенных вертикально (сверху вниз).\n"
        f"Распознай каждый блок ОТДЕЛЬНО.\n"
        f"Формат ответа:\n"
    )
    for i in range(1, len(blocks) + 1):
        batch_instruction += f"[{i}] <результат блока {i}>\n"
    
    batch_instruction += "\nНе объединяй блоки. Каждый блок — отдельный фрагмент документа."
    
    return {
        "system": system,
        "user": user + batch_instruction
    }


def _parse_batch_response(blocks: list, response_text: str) -> dict:
    """
    Парсинг ответа с маркерами [1], [2], ...
    Returns: Dict[block_id -> text]
    """
    import re
    
    results = {}
    
    # Защита от None
    if response_text is None:
        for block in blocks:
            results[block.id] = "[Ошибка: пустой ответ OCR]"
        return results
    
    if len(blocks) == 1:
        results[blocks[0].id] = response_text.strip()
        return results
    
    # Разбиваем по маркерам [N]
    parts = re.split(r'\n?\[(\d+)\]\s*', response_text)
    
    parsed = {}
    for i in range(1, len(parts) - 1, 2):
        try:
            idx = int(parts[i]) - 1  # 1-based -> 0-based
            text = parts[i + 1].strip()
            if 0 <= idx < len(blocks):
                parsed[idx] = text
        except (ValueError, IndexError):
            continue
    
    for i, block in enumerate(blocks):
        if i in parsed:
            results[block.id] = parsed[i]
        else:
            if i == 0 and not parsed:
                results[block.id] = response_text.strip()
            else:
                results[block.id] = "[Ошибка парсинга]"
    
    return results


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
        job_settings_path = job_dir / "job_settings.json"
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
        from rd_core.models import Block, BlockType
        from rd_core.cropping import crop_and_merge_blocks_from_pdf
        from rd_core.ocr import create_ocr_engine
        from PIL import Image
        
        # Восстанавливаем блоки
        blocks = [Block.from_dict(b) for b in blocks_data]
        total_blocks = len(blocks)
        
        logger.info(f"Задача {job.id}: {total_blocks} блоков")
        
        # Вырезаем кропы с объединением TEXT/TABLE в полосы
        update_job_status(job.id, "processing", progress=0.1)
        strip_paths, strip_images, strips, image_blocks = crop_and_merge_blocks_from_pdf(
            str(pdf_path), blocks, str(crops_dir)
        )
        
        logger.info(f"Создано {len(strips)} полос TEXT/TABLE, {len(image_blocks)} IMAGE блоков")
        
        # Загружаем настройки задачи (модели по типам блоков)
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

        # Создаём OCR движки (TEXT/TABLE отдельно от IMAGE)
        engine = job.engine or "openrouter"
        
        if engine == "datalab" and settings.datalab_api_key:
            strip_backend = create_ocr_engine("datalab", api_key=settings.datalab_api_key)
        elif settings.openrouter_api_key:
            strip_model = text_model or table_model or "qwen/qwen3-vl-30b-a3b-instruct"
            strip_backend = create_ocr_engine("openrouter", api_key=settings.openrouter_api_key, model_name=strip_model)
        else:
            strip_backend = create_ocr_engine("dummy")

        if settings.openrouter_api_key:
            img_model = image_model or text_model or table_model or "qwen/qwen3-vl-30b-a3b-instruct"
            image_backend = create_ocr_engine("openrouter", api_key=settings.openrouter_api_key, model_name=img_model)
        else:
            image_backend = create_ocr_engine("dummy")
        
        # Считаем общее количество запросов
        total_requests = len(strips) + len(image_blocks)
        processed = 0
        
        def _update_progress():
            nonlocal processed
            processed += 1
            if total_requests > 0:
                progress = 0.1 + 0.8 * (processed / total_requests)
                update_job_status(job.id, "processing", progress=progress)
        
        # Обрабатываем полосы TEXT/TABLE
        for strip_idx, strip in enumerate(strips):
            try:
                logger.info(f"Обработка полосы {strip_idx + 1}/{len(strips)}: {len(strip.blocks)} блоков")
                merged_image = strip_images.get(strip.strip_id)
                if not merged_image:
                    logger.warning(f"Нет изображения для полосы {strip.strip_id}")
                    _update_progress()
                    continue
                
                # Формируем batch-промпт для полосы
                prompt_data = _build_strip_prompt(strip.blocks)
                
                try:
                    response_text = strip_backend.recognize(merged_image, prompt=prompt_data)
                except Exception as ocr_err:
                    logger.error(f"Ошибка OCR для полосы {strip_idx + 1}: {ocr_err}")
                    response_text = None
                
                # Парсим результаты по маркерам [1], [2], ...
                results = _parse_batch_response(strip.blocks, response_text)
                
                for block in strip.blocks:
                    if block.id in results:
                        block.ocr_text = results[block.id]
                        logger.debug(f"Блок {block.id}: OCR {len(block.ocr_text) if block.ocr_text else 0} символов")
                
                _update_progress()
                
            except Exception as e:
                logger.error(f"Ошибка обработки полосы {strip_idx + 1}: {e}", exc_info=True)
                _update_progress()
        
        # Обрабатываем IMAGE блоки отдельно с их промптами
        for img_idx, (block, crop) in enumerate(image_blocks):
            try:
                logger.info(f"Обработка IMAGE блока {img_idx + 1}/{len(image_blocks)}: {block.id}")
                
                # Используем промпт из блока (если задан клиентом)
                prompt_data = block.prompt
                if not prompt_data:
                    prompt_data = {"system": "", "user": "Опиши что изображено на картинке."}
                
                text = image_backend.recognize(crop, prompt=prompt_data)
                block.ocr_text = text
                logger.debug(f"IMAGE блок {block.id}: {len(text)} символов")
                
                _update_progress()
                
            except Exception as e:
                logger.error(f"Ошибка OCR для IMAGE блока {block.id}: {e}")
                block.ocr_text = f"[Ошибка: {e}]"
                _update_progress()
        
        logger.info(f"OCR завершён: {processed} запросов обработано")
        
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
                
                # Удаляем все файлы включая result.zip
                files_to_remove = [
                    pdf_path,  # document.pdf
                    blocks_path,  # blocks.json
                    result_md_path,  # result.md
                    annotation_path,  # annotation.json
                    result_zip_path,  # result.zip
                ]
                
                for file_path in files_to_remove:
                    if file_path.exists():
                        file_path.unlink()
                        logger.debug(f"  Удалён: {file_path.name}")
                
                # Удаляем папку с кропами
                if crops_dir.exists():
                    shutil.rmtree(crops_dir)
                    logger.debug(f"  Удалена папка: crops/")
                
                logger.info(f"✅ Файлы задачи {job.id} полностью очищены с сервера")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка очистки файлов задачи {job.id}: {e}")
        
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
        from rd_core.models import Document  # noqa: E402
        json.dump(Document(pdf_path=pdf_path.name, pages=[]).to_dict(), f, ensure_ascii=False, indent=2)
    
    with zipfile.ZipFile(result_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(result_md_path, "result.md")
        zf.write(annotation_path, "annotation.json")
        if pdf_path.exists():
            zf.write(pdf_path, "document.pdf")
