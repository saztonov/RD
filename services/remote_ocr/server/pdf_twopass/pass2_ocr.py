"""
PASS 2: OCR с загрузкой кропов с диска.

Параллельная обработка с ограничением потоков.
"""
from __future__ import annotations

import gc
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PIL import Image

from ..logging_config import get_logger
from ..manifest_models import CropManifestEntry, StripManifestEntry, TwoPassManifest
from ..memory_utils import force_gc, log_memory, log_memory_delta
from ..settings import settings

logger = get_logger(__name__)


def pass2_ocr_from_manifest(
    manifest: TwoPassManifest,
    blocks: List,
    strip_backend,
    image_backend,
    stamp_backend,
    pdf_path: str,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    check_paused: Optional[Callable[[], bool]] = None,
) -> None:
    """
    PASS 2: OCR с загрузкой кропов с диска.

    Параллельная обработка с ограничением потоков.
    Результаты записываются в block.ocr_text
    """
    from ..rate_limiter import get_global_ocr_semaphore
    from ..worker_pdf import extract_pdfplumber_text_for_block
    from ..worker_prompts import (
        build_strip_prompt,
        fill_image_prompt_variables,
        inject_pdfplumber_to_ocr_text,
        parse_batch_response_by_index,
    )

    start_mem = log_memory("PASS2 start")

    total_requests = len(manifest.strips) + len(manifest.image_blocks)
    processed = 0

    blocks_by_id = {b.id: b for b in blocks}

    text_block_parts: Dict[str, Dict[int, str]] = {}
    text_block_total_parts: Dict[str, int] = {}
    image_block_parts: Dict[str, Dict[int, str]] = {}
    image_block_total_parts: Dict[str, int] = {}

    global_sem = get_global_ocr_semaphore(settings.max_global_ocr_requests)
    max_workers = settings.ocr_threads_per_job

    last_block_info = {"info": ""}

    def _update_progress(block_info: str = None):
        nonlocal processed
        processed += 1
        if block_info:
            last_block_info["info"] = block_info
        if on_progress and total_requests > 0:
            on_progress(processed, total_requests, last_block_info["info"])

    # --- Обработка strips ---
    def _process_strip(strip: StripManifestEntry, strip_idx: int):
        if check_paused and check_paused():
            return None

        if not strip.strip_path or not os.path.exists(strip.strip_path):
            logger.warning(f"Strip {strip.strip_id} не найден: {strip.strip_path}")
            return None

        try:
            with Image.open(strip.strip_path) as merged_image:
                strip_blocks = [
                    blocks_by_id[bp["block_id"]]
                    for bp in strip.block_parts
                    if bp["block_id"] in blocks_by_id
                ]

                if not strip_blocks:
                    return None

                prompt_data = build_strip_prompt(strip_blocks)

                block_ids = [bp["block_id"] for bp in strip.block_parts]
                logger.info(
                    f"PASS2: начало обработки strip {strip.strip_id} ({len(strip.block_parts)} блоков): {block_ids}"
                )

                global_sem.acquire()
                try:
                    response_text = strip_backend.recognize(
                        merged_image, prompt=prompt_data
                    )
                finally:
                    global_sem.release()

                response_len = len(response_text) if response_text else 0
                logger.info(f"PASS2: завершена обработка strip {strip.strip_id}, ответ {response_len} символов")

            index_results = parse_batch_response_by_index(
                len(strip.block_parts), response_text, block_ids=block_ids
            )

            parsed_lens = {i: len(v) if v else 0 for i, v in index_results.items()}
            logger.info(f"PASS2: strip {strip.strip_id} парсинг результата: {parsed_lens}")

            return strip, index_results, strip_idx

        except Exception as e:
            logger.error(
                f"PASS2: strip processing error {strip.strip_id}",
                extra={
                    "event": "pass2_strip_error",
                    "strip_id": strip.strip_id,
                    "block_ids": [bp["block_id"] for bp in strip.block_parts],
                    "block_count": len(strip.block_parts),
                },
                exc_info=True,
            )
            return None

    logger.info(
        f"PASS2: обработка {len(manifest.strips)} strips ({max_workers} потоков)"
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_strip, strip, idx): strip
            for idx, strip in enumerate(manifest.strips)
        }

        for future in as_completed(futures):
            result = future.result()
            if result:
                strip, index_results, strip_idx = result

                for i, bp in enumerate(strip.block_parts):
                    block_id = bp["block_id"]
                    part_idx = bp["part_idx"]
                    total_parts = bp["total_parts"]
                    text = index_results.get(i, "")

                    if block_id not in text_block_parts:
                        text_block_parts[block_id] = {}
                        text_block_total_parts[block_id] = total_parts

                    text_block_parts[block_id][part_idx] = text

                num_blocks = len(strip.block_parts)
                if num_blocks == 1:
                    suffix = ""
                elif num_blocks < 5:
                    suffix = "а"
                else:
                    suffix = "ов"
                block_info = f"Strip ({num_blocks} блок{suffix})"
                _update_progress(block_info)
            else:
                _update_progress("Strip")
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
        logger.info(
            f"PASS2 TEXT блок {block_id}: ocr_text длина = {len(block.ocr_text) if block.ocr_text else 0}"
        )

    log_memory_delta("PASS2 после strips", start_mem)

    # --- Обработка IMAGE блоков ---
    def _process_image(entry: CropManifestEntry):
        if check_paused and check_paused():
            return None

        block = blocks_by_id.get(entry.block_id)
        if not block:
            return None

        block_code = getattr(block, "code", None)
        backend = stamp_backend if block_code == "stamp" else image_backend

        use_pdf = (
            entry.pdf_crop_path
            and entry.total_parts == 1
            and os.path.exists(entry.pdf_crop_path)
            and hasattr(backend, "supports_pdf_input")
            and backend.supports_pdf_input()
        )

        if not use_pdf and not os.path.exists(entry.crop_path):
            logger.warning(f"Image crop не найден: {entry.crop_path}")
            return None

        try:
            pdfplumber_text = extract_pdfplumber_text_for_block(
                pdf_path, block.page_index, block.coords_norm
            )

            category_id = getattr(block, "category_id", None)
            category_code = getattr(block, "category_code", None)

            prompt_data = fill_image_prompt_variables(
                prompt_data=block.prompt,
                doc_name=Path(pdf_path).name,
                page_index=block.page_index,
                block_id=block.id,
                hint=getattr(block, "hint", None),
                pdfplumber_text=pdfplumber_text,
                category_id=category_id,
                category_code=category_code,
            )

            logger.info(f"PASS2: начало обработки IMAGE блока {entry.block_id}")

            global_sem.acquire()
            try:
                if use_pdf:
                    logger.info(f"PASS2: используется PDF-кроп для {entry.block_id}")
                    text = backend.recognize(
                        image=None,
                        prompt=prompt_data,
                        pdf_file_path=entry.pdf_crop_path,
                    )
                else:
                    with Image.open(entry.crop_path) as crop:
                        text = backend.recognize(crop, prompt=prompt_data)
            finally:
                global_sem.release()

            logger.info(f"PASS2: завершена обработка IMAGE блока {entry.block_id}")

            text = inject_pdfplumber_to_ocr_text(text, pdfplumber_text)
            block.pdfplumber_text = pdfplumber_text

            return entry.block_id, text, entry.part_idx, entry.total_parts

        except Exception as e:
            logger.error(
                f"PASS2: image processing error {entry.block_id}",
                extra={
                    "event": "pass2_image_error",
                    "block_id": entry.block_id,
                    "page_index": entry.page_index,
                    "block_type": entry.block_type,
                    "backend": type(backend).__name__,
                    "use_pdf_crop": use_pdf,
                },
                exc_info=True,
            )
            return entry.block_id, f"[Ошибка: {e}]", entry.part_idx, entry.total_parts

    logger.info(f"PASS2: обработка {len(manifest.image_blocks)} image blocks")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_image, entry): entry
            for entry in manifest.image_blocks
        }

        for future in as_completed(futures):
            result = future.result()
            if result:
                block_id, text, part_idx, total_parts = result

                if block_id not in image_block_parts:
                    image_block_parts[block_id] = {}
                    image_block_total_parts[block_id] = total_parts

                image_block_parts[block_id][part_idx] = text

                block = blocks_by_id.get(block_id)
                if block:
                    page_num = block.page_index + 1
                    category = getattr(block, "category_code", None) or "image"
                    block_info = f"Image: {category} (стр. {page_num})"
                else:
                    block_info = "Image"
                _update_progress(block_info)
            else:
                _update_progress("Image")
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
        logger.info(
            f"PASS2 IMAGE блок {block_id}: ocr_text длина = {len(block.ocr_text) if block.ocr_text else 0}"
        )

    force_gc("PASS2 завершён")
    log_memory_delta("PASS2 end", start_mem)

    logger.info(f"PASS2 завершён: {processed} запросов обработано")
