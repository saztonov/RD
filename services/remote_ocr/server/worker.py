"""Фоновый воркер для обработки OCR задач"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Dict, Any

from .storage import Job, claim_next_job, update_job_status, recover_stuck_jobs
from .settings import settings
from .rate_limiter import get_datalab_limiter

# Настройка логирования для воркера (вывод в stdout)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()

# Кэш извлечённого текста pdfplumber по страницам
_pdfplumber_cache: Dict[str, Dict[int, str]] = {}  # pdf_path -> {page_index: text}


def _extract_pdfplumber_text(pdf_path: str, page_index: int) -> str:
    """
    Извлечь текст со страницы PDF с помощью pdfplumber (с кэшированием)
    
    Args:
        pdf_path: путь к PDF файлу
        page_index: индекс страницы
    
    Returns:
        Извлечённый текст
    """
    global _pdfplumber_cache
    
    # Проверяем кэш
    if pdf_path in _pdfplumber_cache:
        if page_index in _pdfplumber_cache[pdf_path]:
            return _pdfplumber_cache[pdf_path][page_index]
    else:
        _pdfplumber_cache[pdf_path] = {}
    
    try:
        from rd_core.pdf_utils import extract_full_page_text
        text = extract_full_page_text(pdf_path, page_index)
        _pdfplumber_cache[pdf_path][page_index] = text
        return text
    except Exception as e:
        logger.warning(f"Ошибка извлечения текста pdfplumber для страницы {page_index}: {e}")
        return ""


def _fill_image_prompt_variables(
    prompt_data: Optional[dict],
    doc_name: str,
    page_index: int,
    block_id: str,
    hint: Optional[str],
    pdfplumber_text: str
) -> dict:
    """
    Заполнить переменные в промпте для IMAGE блока
    
    Переменные:
        {DOC_NAME} - имя PDF документа
        {PAGE_OR_NULL} - номер страницы (1-based) или "null"
        {TILE_ID_OR_NULL} - ID блока или "null"
        {TILE_HINT_OR_NULL} - подсказка пользователя или "null"
        {OPERATOR_HINT_OR_EMPTY} - подсказка пользователя или пустая строка
        {PDFPLUMBER_TEXT_OR_EMPTY} - извлечённый текст pdfplumber
    
    Args:
        prompt_data: исходный промпт {"system": "...", "user": "..."}
        doc_name: имя документа
        page_index: индекс страницы (0-based)
        block_id: ID блока
        hint: подсказка пользователя
        pdfplumber_text: извлечённый текст pdfplumber
    
    Returns:
        Промпт с заполненными переменными
    """
    if not prompt_data:
        return {"system": "", "user": "Опиши что изображено на картинке."}
    
    # Копируем промпт
    result = {
        "system": prompt_data.get("system", ""),
        "user": prompt_data.get("user", "")
    }
    
    # Значения для подстановки
    variables = {
        "{DOC_NAME}": doc_name or "unknown",
        "{PAGE_OR_NULL}": str(page_index + 1) if page_index is not None else "null",
        "{TILE_ID_OR_NULL}": block_id or "null",
        "{TILE_HINT_OR_NULL}": hint if hint else "null",
        "{OPERATOR_HINT_OR_EMPTY}": hint if hint else "",
        "{PDFPLUMBER_TEXT_OR_EMPTY}": pdfplumber_text or "",
    }
    
    # Подставляем переменные
    for key, value in variables.items():
        result["system"] = result["system"].replace(key, value)
        result["user"] = result["user"].replace(key, value)
    
    return result


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


def _parse_batch_response_by_index(num_blocks: int, response_text: str) -> Dict[int, str]:
    """
    Парсинг ответа с маркерами [1], [2], ...
    Returns: Dict[index -> text] (индекс 0-based)
    """
    import re
    
    results: Dict[int, str] = {}
    
    # Защита от None
    if response_text is None:
        for i in range(num_blocks):
            results[i] = "[Ошибка: пустой ответ OCR]"
        return results
    
    if num_blocks == 1:
        results[0] = response_text.strip()
        return results
    
    # Разбиваем по маркерам [N]
    parts = re.split(r'\n?\[(\d+)\]\s*', response_text)
    
    parsed = {}
    for i in range(1, len(parts) - 1, 2):
        try:
            idx = int(parts[i]) - 1  # 1-based -> 0-based
            text = parts[i + 1].strip()
            if 0 <= idx < num_blocks:
                parsed[idx] = text
        except (ValueError, IndexError):
            continue
    
    # Если маркеров не найдено - пробуем разделить по разделителям
    if not parsed:
        # Пробуем разделить по "---" или пустым строкам (2+)
        alt_parts = re.split(r'\n{3,}|(?:\n-{3,}\n)', response_text.strip())
        if len(alt_parts) >= num_blocks:
            for i in range(num_blocks):
                results[i] = alt_parts[i].strip()
            return results
        # Fallback: весь текст идёт первому элементу, остальные пусты
        for i in range(num_blocks):
            if i == 0:
                results[i] = response_text.strip()
            else:
                results[i] = ""  # Пустой результат вместо ошибки
        logger.warning(f"Batch response без маркеров [N], весь текст присвоен первому элементу")
        return results
    
    for i in range(num_blocks):
        if i in parsed:
            results[i] = parsed[i]
        else:
            # Для непарсенных элементов - пустой результат вместо ошибки
            results[i] = ""
            logger.warning(f"Элемент {i} не найден в batch response")
    
    return results


def start_worker() -> None:
    """Запустить фоновый воркер"""
    global _worker_thread
    
    if _worker_thread is not None and _worker_thread.is_alive():
        logger.warning("Worker уже запущен")
        print("[WORKER] Worker уже запущен", flush=True)
        return
    
    # Восстанавливаем застрявшие задачи при старте
    recovered = recover_stuck_jobs()
    if recovered > 0:
        print(f"[WORKER] Восстановлено {recovered} застрявших задач", flush=True)
    
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="ocr-worker")
    _worker_thread.start()
    logger.info("OCR Worker запущен")
    print("[WORKER] OCR Worker запущен", flush=True)


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
    print("[WORKER] Worker loop started", flush=True)
    while not _stop_event.is_set():
        try:
            job = claim_next_job()
            if job:
                logger.info(f"Взята задача {job.id}")
                print(f"[WORKER] Взята задача {job.id}", flush=True)
                _process_job(job)
            else:
                time.sleep(2.0)
        except Exception as e:
            logger.error(f"Ошибка в worker loop: {e}")
            print(f"[WORKER] Ошибка: {e}", flush=True)
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
        
        # Логируем распределение блоков по страницам
        pages_summary = {}
        for b in blocks:
            pages_summary[b.page_index] = pages_summary.get(b.page_index, 0) + 1
        logger.info(f"Распределение блоков по страницам: {pages_summary}")
        
        # Вырезаем кропы с объединением TEXT/TABLE в полосы
        # IMAGE блоки сохраняем как PDF (векторный формат)
        update_job_status(job.id, "processing", progress=0.1)
        strip_paths, strip_images, strips, image_blocks, image_pdf_paths = crop_and_merge_blocks_from_pdf(
            str(pdf_path), blocks, str(crops_dir), save_image_crops_as_pdf=True
        )
        
        logger.info(f"Создано {len(strips)} полос TEXT/TABLE, {len(image_blocks)} IMAGE блоков, {len(image_pdf_paths)} PDF-кропов")
        
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
        
        # Получаем глобальный rate limiter для Datalab
        datalab_limiter = get_datalab_limiter() if engine == "datalab" else None
        
        if engine == "datalab" and settings.datalab_api_key:
            strip_backend = create_ocr_engine(
                "datalab", 
                api_key=settings.datalab_api_key,
                rate_limiter=datalab_limiter
            )
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
                    logger.warning(f"Нет изображения для полосы {strip.strip_id}")
                    return {}, []
                
                # Формируем batch-промпт для полосы
                prompt_data = _build_strip_prompt(strip.blocks)
                
                try:
                    response_text = strip_backend.recognize(merged_image, prompt=prompt_data)
                except Exception as ocr_err:
                    logger.error(f"Ошибка OCR для полосы {strip_idx + 1}: {ocr_err}")
                    response_text = None
                
                # Парсим результаты по индексам
                index_results = _parse_batch_response_by_index(len(strip.blocks), response_text)
                
                # Возвращаем результаты с метаинфо о частях
                return index_results, strip.block_parts
                
            except Exception as e:
                logger.error(f"Ошибка обработки полосы {strip_idx + 1}: {e}", exc_info=True)
                return {}, []
        
        def _process_image_block(img_idx: int, block, crop, part_idx: int, total_parts: int):
            """Обработать один IMAGE блок (или часть)"""
            try:
                part_info = f" (часть {part_idx + 1}/{total_parts})" if total_parts > 1 else ""
                logger.info(f"Обработка IMAGE блока {img_idx + 1}/{len(image_blocks)}: {block.id}{part_info}")
                
                # Извлекаем текст pdfplumber для страницы блока
                pdfplumber_text = _extract_pdfplumber_text(str(pdf_path), block.page_index)
                
                # Получаем имя документа
                doc_name = pdf_path.name
                
                # Используем промпт из блока и заполняем переменные
                prompt_data = block.prompt
                prompt_data = _fill_image_prompt_variables(
                    prompt_data=prompt_data,
                    doc_name=doc_name,
                    page_index=block.page_index,
                    block_id=block.id,
                    hint=getattr(block, 'hint', None),
                    pdfplumber_text=pdfplumber_text
                )
                
                logger.debug(f"IMAGE блок {block.id}: hint={getattr(block, 'hint', None)}, pdfplumber_len={len(pdfplumber_text)}")
                
                text = image_backend.recognize(crop, prompt=prompt_data)
                return block.id, text, part_idx, total_parts
                
            except Exception as e:
                logger.error(f"Ошибка OCR для IMAGE блока {block.id}: {e}")
                return block.id, f"[Ошибка: {e}]", part_idx, total_parts
        
        # Параллельная обработка полос TEXT/TABLE
        max_workers = settings.datalab_max_concurrent if engine == "datalab" else 5
        logger.info(f"Запуск параллельной обработки: {len(strips)} полос, {len(image_blocks)} IMAGE, max_workers={max_workers}")
        
        # Собираем части TEXT/TABLE блоков для объединения результатов
        text_block_parts: Dict[str, Dict[int, str]] = {}  # block_id -> {part_idx: text}
        text_block_total_parts: Dict[str, int] = {}  # block_id -> total_parts
        text_block_objects: Dict[str, object] = {}  # block_id -> block object
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Отправляем strips на обработку
            strip_futures = {
                executor.submit(_process_strip, idx, strip): strip
                for idx, strip in enumerate(strips)
            }
            
            # Собираем результаты strips
            for future in as_completed(strip_futures):
                strip = strip_futures[future]
                try:
                    index_results, block_parts_info = future.result()
                    
                    # Проверяем наличие метаинфо о частях
                    if block_parts_info and len(block_parts_info) == len(strip.blocks):
                        # Обрабатываем результаты с учётом частей блоков
                        for i, block_part in enumerate(block_parts_info):
                            text = index_results.get(i, "")
                            block = block_part.block
                            block_id = block.id
                            part_idx = block_part.part_idx
                            total_parts = block_part.total_parts
                            
                            # Инициализируем структуры для блока
                            if block_id not in text_block_parts:
                                text_block_parts[block_id] = {}
                                text_block_total_parts[block_id] = total_parts
                                text_block_objects[block_id] = block
                            
                            # Сохраняем результат части
                            text_block_parts[block_id][part_idx] = text
                            logger.debug(f"TEXT/TABLE блок {block_id} часть {part_idx + 1}/{total_parts}: {len(text)} символов")
                    else:
                        # Fallback: обрабатываем без метаинфо о частях (старый способ)
                        seen_blocks = set()
                        for i, block in enumerate(strip.blocks):
                            if block.id not in seen_blocks:
                                text = index_results.get(i, "")
                                block.ocr_text = text
                                seen_blocks.add(block.id)
                                logger.debug(f"Блок {block.id}: OCR {len(text)} символов")
                except Exception as e:
                    logger.error(f"Ошибка получения результата полосы: {e}")
                finally:
                    _update_progress()
        
        # Объединяем результаты частей для TEXT/TABLE блоков
        for block_id, parts_dict in text_block_parts.items():
            block = text_block_objects[block_id]
            total_parts = text_block_total_parts[block_id]
            
            if total_parts == 1:
                block.ocr_text = parts_dict.get(0, "")
            else:
                # Объединяем части в правильном порядке
                combined_parts = []
                for i in range(total_parts):
                    if i in parts_dict:
                        combined_parts.append(parts_dict[i])
                    else:
                        logger.warning(f"Отсутствует часть {i + 1}/{total_parts} для TEXT/TABLE блока {block_id}")
                
                block.ocr_text = "\n\n".join(combined_parts)
                logger.info(f"Объединено {len(combined_parts)}/{total_parts} частей для TEXT/TABLE блока {block_id}")
        
        # Параллельная обработка IMAGE блоков
        # Собираем части блоков для объединения результатов
        block_parts_results: Dict[str, Dict[int, str]] = {}  # block_id -> {part_idx: text}
        block_total_parts: Dict[str, int] = {}  # block_id -> total_parts
        block_objects: Dict[str, object] = {}  # block_id -> block object
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            image_futures = {
                executor.submit(_process_image_block, idx, block, crop, part_idx, total_parts): (block, part_idx, total_parts)
                for idx, (block, crop, part_idx, total_parts) in enumerate(image_blocks)
            }
            
            # Собираем результаты IMAGE блоков
            for future in as_completed(image_futures):
                block, part_idx, total_parts = image_futures[future]
                try:
                    block_id, text, res_part_idx, res_total_parts = future.result()
                    
                    # Инициализируем структуры для блока
                    if block_id not in block_parts_results:
                        block_parts_results[block_id] = {}
                        block_total_parts[block_id] = res_total_parts
                        block_objects[block_id] = block
                    
                    # Сохраняем результат части
                    block_parts_results[block_id][res_part_idx] = text
                    logger.debug(f"IMAGE блок {block_id} часть {res_part_idx + 1}/{res_total_parts}: {len(text) if text else 0} символов")
                except Exception as e:
                    logger.error(f"Ошибка получения результата IMAGE: {e}")
                    block.ocr_text = f"[Ошибка: {e}]"
                finally:
                    _update_progress()
        
        # Объединяем результаты частей для каждого блока
        for block_id, parts_dict in block_parts_results.items():
            block = block_objects[block_id]
            total_parts = block_total_parts[block_id]
            
            if total_parts == 1:
                block.ocr_text = parts_dict.get(0, "")
            else:
                # Объединяем части в правильном порядке
                combined_parts = []
                for i in range(total_parts):
                    if i in parts_dict:
                        combined_parts.append(parts_dict[i])
                    else:
                        logger.warning(f"Отсутствует часть {i + 1}/{total_parts} для блока {block_id}")
                
                block.ocr_text = "\n\n".join(combined_parts)
                logger.info(f"Объединено {len(combined_parts)}/{total_parts} частей для IMAGE блока {block_id}")
        
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
            
            # Только PDF-кропы IMAGE блоков (векторный формат)
            # TEXT/TABLE кропы не сохраняем
            if crops_dir.exists():
                for crop_file in crops_dir.iterdir():
                    if crop_file.is_file() and crop_file.suffix.lower() == ".pdf":
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
