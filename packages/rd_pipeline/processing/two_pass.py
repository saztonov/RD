"""
Two-pass OCR algorithm with minimal memory consumption.

PASS 1: Prepare crops -> save to disk
PASS 2: OCR with loading one crop at a time from disk

Server-specific logic (prompts, text extraction) is passed via callbacks.
"""
from __future__ import annotations

import gc
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional, Protocol, Tuple, Any

from PIL import Image

from rd_domain.manifest import CropManifestEntry, TwoPassManifest
from rd_pipeline.utils.memory import force_gc, log_memory, log_memory_delta
from rd_pipeline.processing.streaming_pdf import (
    StreamingPDFProcessor,
    render_block_crop,
    split_large_crop,
)
from rd_pipeline.processing.config import ProcessingConfig, default_config
from rd_pipeline.processing.image_preprocessing import (
    PreprocessMode,
    get_preprocess_mode_for_block,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Protocol definitions for server-specific callbacks
# ============================================================================

class PromptBuilder(Protocol):
    """Protocol for building OCR prompts."""

    def build_strip_prompt(self, blocks: List) -> dict:
        """Build prompt for strip OCR."""
        ...

    def fill_image_prompt_variables(
        self,
        prompt_data: Optional[dict],
        doc_name: str,
        page_index: int,
        block_id: str,
        hint: Optional[str] = None,
        pdfplumber_text: Optional[str] = None,
        category_id: Optional[str] = None,
        category_code: Optional[str] = None,
    ) -> dict:
        """Fill variables in image prompt."""
        ...

    def inject_pdfplumber_to_ocr_text(
        self,
        ocr_text: str,
        pdfplumber_text: Optional[str],
    ) -> str:
        """Inject pdfplumber text into OCR result."""
        ...


class TextExtractor(Protocol):
    """Protocol for extracting text from PDF."""

    def extract_pdfplumber_text_for_block(
        self,
        pdf_path: str,
        page_index: int,
        coords_norm: Tuple[float, float, float, float],
    ) -> Optional[str]:
        """Extract text from PDF using pdfplumber."""
        ...


# ============================================================================
# Default implementations (no-op)
# ============================================================================

class DefaultPromptBuilder:
    """Default prompt builder that returns empty dicts."""

    def build_strip_prompt(self, blocks: List) -> dict:
        return {}

    def fill_image_prompt_variables(
        self,
        prompt_data: Optional[dict],
        doc_name: str,
        page_index: int,
        block_id: str,
        hint: Optional[str] = None,
        pdfplumber_text: Optional[str] = None,
        category_id: Optional[str] = None,
        category_code: Optional[str] = None,
    ) -> dict:
        return prompt_data or {}

    def inject_pdfplumber_to_ocr_text(
        self,
        ocr_text: str,
        pdfplumber_text: Optional[str],
    ) -> str:
        return ocr_text


class DefaultTextExtractor:
    """Default text extractor that returns None."""

    def extract_pdfplumber_text_for_block(
        self,
        pdf_path: str,
        page_index: int,
        coords_norm: Tuple[float, float, float, float],
    ) -> Optional[str]:
        return None


# ============================================================================
# PASS 1: Prepare crops
# ============================================================================

def pass1_prepare_crops(
    pdf_path: str,
    blocks: List,
    crops_dir: str,
    padding: int = 5,
    save_image_crops_as_pdf: bool = True,
    on_progress: Optional[Callable[[int, int], None]] = None,
    config: Optional[ProcessingConfig] = None,
) -> TwoPassManifest:
    """
    PASS 1: Crop all blocks and save to disk.

    Groups TEXT/TABLE blocks into strips, IMAGE blocks saved separately.
    Uses clip-rendering for efficient processing of large sheets (A0/A1).
    """
    from rd_domain.models import BlockType, ShapeType

    cfg = config or default_config
    os.makedirs(crops_dir, exist_ok=True)
    strips_dir = os.path.join(crops_dir, "strips")
    images_dir = os.path.join(crops_dir, "images")
    os.makedirs(strips_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    start_mem = log_memory(
        f"PASS1 start (PDF: {os.path.getsize(pdf_path) / 1024 / 1024:.1f} MB)"
    )

    # === ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ ВХОДНЫХ БЛОКОВ ===
    logger.info(f"PASS1: получено {len(blocks)} блоков для обработки")
    for i, b in enumerate(blocks):
        logger.info(
            f"  PASS1 input block [{i}]: id={b.id}, page={b.page_index}, "
            f"type={b.block_type.value}, coords_norm={b.coords_norm}"
        )

    # Group blocks by page
    blocks_by_page: Dict[int, List] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page_index, []).append(block)

    logger.info(f"PASS1: блоки сгруппированы по {len(blocks_by_page)} страницам")
    for page_idx, page_blocks in blocks_by_page.items():
        block_ids = [b.id for b in page_blocks]
        logger.info(f"  PASS1 page {page_idx}: {len(page_blocks)} блоков: {block_ids}")

    # Temporary storage for crop paths
    block_crop_paths: Dict[str, List[Tuple[str, int, int]]] = {}
    text_block_entries: List[CropManifestEntry] = []  # NEW: individual TEXT crops
    image_block_entries: List[CropManifestEntry] = []
    image_pdf_paths: Dict[str, str] = {}

    processed_pages = 0
    total_pages = len(blocks_by_page)

    compress_level = cfg.crop_png_compress

    with StreamingPDFProcessor(pdf_path, config=cfg) as processor:
        logger.info(f"PASS1: {processor.page_count} pages, {len(blocks)} blocks")

        for page_idx in sorted(blocks_by_page.keys()):
            page_blocks = blocks_by_page[page_idx]

            for block in page_blocks:
                try:
                    logger.info(
                        f"PASS1: cropping block {block.id} (page={block.page_index}, "
                        f"type={block.block_type.value}, coords_norm={block.coords_norm})"
                    )

                    # Determine preprocessing mode based on block type
                    ocr_prep_mode = None
                    if cfg.ocr_prep_enabled:
                        preprocess_mode = get_preprocess_mode_for_block(block)
                        if preprocess_mode != PreprocessMode.NONE:
                            # Map PreprocessMode to string for render_block_crop
                            ocr_prep_mode = preprocess_mode.value

                    crop = render_block_crop(
                        pdf_path=pdf_path,
                        page_index=block.page_index,
                        coords_norm=block.coords_norm,
                        target_dpi=cfg.pdf_render_dpi,
                        max_dimension=cfg.max_crop_dimension,
                        min_dpi=cfg.min_crop_dpi,
                        padding_pt=padding,
                        ocr_prep=ocr_prep_mode,
                        ocr_prep_contrast=cfg.ocr_prep_contrast,
                        polygon_points=block.polygon_points if block.shape_type == ShapeType.POLYGON else None,
                        polygon_coords_px=block.coords_px if block.shape_type == ShapeType.POLYGON else None,
                    )
                    if not crop:
                        logger.warning(f"PASS1: render_block_crop returned None for block {block.id}")
                        continue

                    logger.info(f"PASS1: block {block.id} crop size: {crop.width}x{crop.height}")

                    crop_parts = split_large_crop(crop, cfg.max_single_block_height, config=cfg)
                    total_parts = len(crop_parts)

                    block_crop_paths[block.id] = []

                    for part_idx, crop_part in enumerate(crop_parts):
                        if block.block_type == BlockType.IMAGE:
                            crop_filename = f"{block.id}_p{part_idx}.png"
                            crop_path = os.path.join(images_dir, crop_filename)
                        else:
                            crop_filename = f"{block.id}_p{part_idx}.png"
                            crop_path = os.path.join(crops_dir, crop_filename)

                        crop_part.save(crop_path, "PNG", compress_level=compress_level)

                        block_crop_paths[block.id].append(
                            (crop_path, part_idx, total_parts)
                        )

                        if block.block_type == BlockType.IMAGE:
                            image_block_entries.append(
                                CropManifestEntry(
                                    block_id=block.id,
                                    crop_path=crop_path,
                                    block_type=block.block_type.value,
                                    page_index=block.page_index,
                                    part_idx=part_idx,
                                    total_parts=total_parts,
                                    width=crop_part.width,
                                    height=crop_part.height,
                                )
                            )
                        else:
                            # TEXT/TABLE blocks - save as individual crops (not merged into strips)
                            text_block_entries.append(
                                CropManifestEntry(
                                    block_id=block.id,
                                    crop_path=crop_path,
                                    block_type=block.block_type.value,
                                    page_index=block.page_index,
                                    part_idx=part_idx,
                                    total_parts=total_parts,
                                    width=crop_part.width,
                                    height=crop_part.height,
                                )
                            )

                        crop_part.close()

                    if total_parts > 1:
                        crop.close()

                    if save_image_crops_as_pdf and block.block_type == BlockType.IMAGE:
                        pdf_crop_path = os.path.join(images_dir, f"{block.id}.pdf")
                        result = processor.crop_block_to_pdf(
                            block, pdf_crop_path, padding_pt=2
                        )
                        if result:
                            image_pdf_paths[block.id] = result
                            block.image_file = result
                            for entry in image_block_entries:
                                if entry.block_id == block.id and entry.part_idx == 0:
                                    entry.pdf_crop_path = result
                                    break

                except Exception as e:
                    logger.error(f"PASS1: block error {block.id}: {e}")

            processed_pages += 1
            if on_progress:
                on_progress(processed_pages, total_pages)

            gc.collect()

        log_memory_delta("PASS1 after crops", start_mem)

    # NOTE: strips are DEPRECATED - each TEXT block is now processed individually
    # No more merging into strips, no more removing intermediate crops

    manifest = TwoPassManifest(
        pdf_path=pdf_path,
        crops_dir=crops_dir,
        text_blocks=text_block_entries,
        image_blocks=image_block_entries,
        total_blocks=len(blocks),
    )

    manifest_path = os.path.join(crops_dir, "manifest.json")
    manifest.save(manifest_path)

    force_gc("PASS1 complete")
    log_memory_delta("PASS1 end", start_mem)

    logger.info(
        f"PASS1 complete: {len(text_block_entries)} text crops, {len(image_block_entries)} image crops"
    )

    return manifest


# ============================================================================
# PASS 2: OCR from manifest
# ============================================================================

def pass2_ocr_from_manifest(
    manifest: TwoPassManifest,
    blocks: List,
    strip_backend,
    image_backend,
    stamp_backend,
    pdf_path: str,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    check_paused: Optional[Callable[[], bool]] = None,
    prompt_builder: Optional[PromptBuilder] = None,
    text_extractor: Optional[TextExtractor] = None,
    config: Optional[ProcessingConfig] = None,
) -> None:
    """
    PASS 2: OCR with loading crops from disk.

    Parallel processing with thread limit.
    Results are written to block.ocr_text
    """
    cfg = config or default_config
    pb = prompt_builder or DefaultPromptBuilder()
    te = text_extractor or DefaultTextExtractor()

    start_mem = log_memory("PASS2 start")

    # Use text_blocks instead of deprecated strips
    total_requests = len(manifest.text_blocks) + len(manifest.image_blocks)
    processed = 0

    blocks_by_id = {b.id: b for b in blocks}

    text_block_parts: Dict[str, Dict[int, str]] = {}
    text_block_total_parts: Dict[str, int] = {}
    image_block_parts: Dict[str, Dict[int, str]] = {}
    image_block_total_parts: Dict[str, int] = {}

    max_workers = cfg.ocr_threads_per_job

    last_block_info = {"info": ""}

    def _update_progress(block_info: str = None):
        nonlocal processed
        processed += 1
        if block_info:
            last_block_info["info"] = block_info
        if on_progress and total_requests > 0:
            on_progress(processed, total_requests, last_block_info["info"])

    # --- Process TEXT blocks (individual crops, no batch) ---
    # Retry configuration for timeout blocks
    MAX_TIMEOUT_RETRIES = 3

    def _process_text_block(entry: CropManifestEntry):
        if check_paused and check_paused():
            return None

        if not os.path.exists(entry.crop_path):
            logger.warning(f"Text crop not found: {entry.crop_path}")
            return None

        block = blocks_by_id.get(entry.block_id)
        if not block:
            return None

        try:
            logger.info(f"PASS2: processing TEXT block {entry.block_id}")

            with Image.open(entry.crop_path) as crop:
                # Simple prompt for single block (no batch markers needed)
                prompt_data = pb.build_strip_prompt([block])

                # Retry loop with increasing timeout multiplier
                text = None
                for retry_attempt in range(MAX_TIMEOUT_RETRIES):
                    timeout_multiplier = retry_attempt + 1  # 1x, 2x, 3x
                    text = strip_backend.recognize(
                        crop, prompt=prompt_data, timeout_multiplier=timeout_multiplier
                    )

                    if text != "[TIMEOUT]":
                        break

                    if retry_attempt < MAX_TIMEOUT_RETRIES - 1:
                        logger.warning(
                            f"PASS2: TEXT block {entry.block_id} timeout, "
                            f"retry {retry_attempt + 1}/{MAX_TIMEOUT_RETRIES} "
                            f"with multiplier {timeout_multiplier + 1}x"
                        )

            # Check for final timeout after all retries
            if text == "[TIMEOUT]":
                logger.error(
                    f"PASS2: TEXT block {entry.block_id} got TIMEOUT after "
                    f"{MAX_TIMEOUT_RETRIES} retries (crop size: {entry.crop_path})"
                )
                text = ""

            logger.info(f"PASS2: completed TEXT block {entry.block_id}, response {len(text) if text else 0} chars")

            return entry.block_id, text, entry.part_idx, entry.total_parts

        except Exception as e:
            logger.error(f"PASS2 text {entry.block_id}: {e}")
            return entry.block_id, f"[Error: {e}]", entry.part_idx, entry.total_parts

    logger.info(
        f"PASS2: processing {len(manifest.text_blocks)} text blocks ({max_workers} threads)"
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_text_block, entry): entry
            for entry in manifest.text_blocks
        }

        for future in as_completed(futures):
            result = future.result()
            if result:
                block_id, text, part_idx, total_parts = result

                if block_id not in text_block_parts:
                    text_block_parts[block_id] = {}
                    text_block_total_parts[block_id] = total_parts

                text_block_parts[block_id][part_idx] = text

                block = blocks_by_id.get(block_id)
                if block:
                    page_num = block.page_index + 1
                    block_info = f"Text (page {page_num})"
                else:
                    block_info = "Text"
                _update_progress(block_info)
            else:
                _update_progress("Text")
            gc.collect()

    # Assemble TEXT/TABLE block parts
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
            f"PASS2 TEXT block {block_id}: ocr_text length = {len(block.ocr_text) if block.ocr_text else 0}"
        )

    log_memory_delta("PASS2 after text blocks", start_mem)

    # --- Process IMAGE blocks ---
    def _process_image(entry: CropManifestEntry):
        if check_paused and check_paused():
            return None

        if not os.path.exists(entry.crop_path):
            logger.warning(f"Image crop not found: {entry.crop_path}")
            return None

        block = blocks_by_id.get(entry.block_id)
        if not block:
            return None

        try:
            pdfplumber_text = te.extract_pdfplumber_text_for_block(
                pdf_path, block.page_index, block.coords_norm
            )

            category_id = getattr(block, "category_id", None)
            category_code = getattr(block, "category_code", None)

            prompt_data = pb.fill_image_prompt_variables(
                prompt_data=block.prompt,
                doc_name=Path(pdf_path).name,
                page_index=block.page_index,
                block_id=block.id,
                hint=getattr(block, "hint", None),
                pdfplumber_text=pdfplumber_text,
                category_id=category_id,
                category_code=category_code,
            )

            block_code = getattr(block, "code", None)
            backend = stamp_backend if block_code == "stamp" else image_backend

            logger.info(f"PASS2: processing IMAGE block {entry.block_id}")

            use_native_pdf = (
                entry.pdf_crop_path
                and entry.total_parts == 1
                and os.path.exists(entry.pdf_crop_path)
                and hasattr(backend, "supports_native_pdf")
                and backend.supports_native_pdf()
            )

            # Retry loop with increasing timeout multiplier for IMAGE blocks
            text = None
            for retry_attempt in range(MAX_TIMEOUT_RETRIES):
                timeout_multiplier = retry_attempt + 1  # 1x, 2x, 3x

                if use_native_pdf:
                    logger.info(f"PASS2: native PDF for {entry.block_id}")
                    text = backend.recognize_pdf(
                        entry.pdf_crop_path, prompt=prompt_data,
                        timeout_multiplier=timeout_multiplier
                    )
                else:
                    with Image.open(entry.crop_path) as crop:
                        text = backend.recognize(
                            crop, prompt=prompt_data,
                            timeout_multiplier=timeout_multiplier
                        )

                if text != "[TIMEOUT]":
                    break

                if retry_attempt < MAX_TIMEOUT_RETRIES - 1:
                    logger.warning(
                        f"PASS2: IMAGE block {entry.block_id} timeout, "
                        f"retry {retry_attempt + 1}/{MAX_TIMEOUT_RETRIES} "
                        f"with multiplier {timeout_multiplier + 1}x"
                    )

            # Check for final timeout after all retries
            if text == "[TIMEOUT]":
                logger.error(
                    f"PASS2: IMAGE block {entry.block_id} got TIMEOUT after "
                    f"{MAX_TIMEOUT_RETRIES} retries"
                )
                text = ""

            logger.info(f"PASS2: completed IMAGE block {entry.block_id}")

            text = pb.inject_pdfplumber_to_ocr_text(text, pdfplumber_text)
            block.pdfplumber_text = pdfplumber_text

            return entry.block_id, text, entry.part_idx, entry.total_parts

        except Exception as e:
            logger.error(f"PASS2 image {entry.block_id}: {e}")
            return entry.block_id, f"[Error: {e}]", entry.part_idx, entry.total_parts

    logger.info(f"PASS2: processing {len(manifest.image_blocks)} image blocks")

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
                    block_info = f"Image: {category} (page {page_num})"
                else:
                    block_info = "Image"
                _update_progress(block_info)
            else:
                _update_progress("Image")
            gc.collect()

    # Assemble IMAGE block parts
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
            f"PASS2 IMAGE block {block_id}: ocr_text length = {len(block.ocr_text) if block.ocr_text else 0}"
        )

    force_gc("PASS2 complete")
    log_memory_delta("PASS2 end", start_mem)

    logger.info(f"PASS2 complete: {processed} requests processed")


def cleanup_manifest_files(manifest: TwoPassManifest) -> None:
    """Delete all temporary files after processing."""
    try:
        crops_dir = manifest.crops_dir
        if os.path.exists(crops_dir):
            shutil.rmtree(crops_dir)
            logger.info(f"Deleted crops directory: {crops_dir}")
    except Exception as e:
        logger.warning(f"Error deleting crops: {e}")
