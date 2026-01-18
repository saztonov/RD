"""
DEPRECATED: Import from rd_pipeline.processing.two_pass instead.

This module is a backward compatibility shim that uses server-specific
prompt builders and text extractors.
"""
from __future__ import annotations

import warnings
from typing import Callable, List, Optional

warnings.warn(
    "apps.remote_ocr_server.pdf_streaming_twopass is deprecated. "
    "Use rd_pipeline.processing.two_pass instead.",
    DeprecationWarning,
    stacklevel=2,
)

from rd_domain.manifest import TwoPassManifest
from rd_pipeline.processing.config import ProcessingConfig
from rd_pipeline.processing.two_pass import (
    pass1_prepare_crops as _pass1_prepare_crops,
    pass2_ocr_from_manifest as _pass2_ocr_from_manifest,
    cleanup_manifest_files,
    PromptBuilder,
    TextExtractor,
)
from .settings import settings

# Server-specific config
_server_config = ProcessingConfig(
    pdf_render_dpi=settings.pdf_render_dpi,
    crop_png_compress=settings.crop_png_compress,
    max_crop_dimension=settings.max_crop_dimension,
    min_crop_dpi=settings.min_crop_dpi,
    ocr_prep_enabled=settings.ocr_prep_enabled,
    ocr_prep_contrast=settings.ocr_prep_contrast,
    ocr_threads_per_job=settings.ocr_threads_per_job,
)


class ServerPromptBuilder:
    """Server-specific prompt builder using worker_prompts."""

    def build_strip_prompt(self, blocks: List) -> dict:
        from .worker_prompts import build_strip_prompt
        return build_strip_prompt(blocks)

    def fill_image_prompt_variables(
        self,
        prompt_data,
        doc_name: str,
        page_index: int,
        block_id: str,
        hint=None,
        pdfplumber_text=None,
        category_id=None,
        category_code=None,
    ) -> dict:
        from .worker_prompts import fill_image_prompt_variables
        return fill_image_prompt_variables(
            prompt_data, doc_name, page_index, block_id,
            hint=hint, pdfplumber_text=pdfplumber_text,
            category_id=category_id, category_code=category_code,
        )

    def inject_pdfplumber_to_ocr_text(self, ocr_text: str, pdfplumber_text):
        from .worker_prompts import inject_pdfplumber_to_ocr_text
        return inject_pdfplumber_to_ocr_text(ocr_text, pdfplumber_text)


class ServerTextExtractor:
    """Server-specific text extractor using worker_pdf."""

    def extract_pdfplumber_text_for_block(
        self, pdf_path: str, page_index: int, coords_norm
    ):
        from .worker_pdf import extract_pdfplumber_text_for_block
        return extract_pdfplumber_text_for_block(pdf_path, page_index, coords_norm)


# Default server instances
_server_prompt_builder = ServerPromptBuilder()
_server_text_extractor = ServerTextExtractor()


def pass1_prepare_crops(
    pdf_path: str,
    blocks: List,
    crops_dir: str,
    padding: int = 5,
    save_image_crops_as_pdf: bool = True,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> TwoPassManifest:
    """Server-configured pass1_prepare_crops."""
    return _pass1_prepare_crops(
        pdf_path=pdf_path,
        blocks=blocks,
        crops_dir=crops_dir,
        padding=padding,
        save_image_crops_as_pdf=save_image_crops_as_pdf,
        on_progress=on_progress,
        config=_server_config,
    )


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
    """Server-configured pass2_ocr_from_manifest."""
    return _pass2_ocr_from_manifest(
        manifest=manifest,
        blocks=blocks,
        strip_backend=strip_backend,
        image_backend=image_backend,
        stamp_backend=stamp_backend,
        pdf_path=pdf_path,
        on_progress=on_progress,
        check_paused=check_paused,
        prompt_builder=_server_prompt_builder,
        text_extractor=_server_text_extractor,
        config=_server_config,
    )


__all__ = [
    "pass1_prepare_crops",
    "pass2_ocr_from_manifest",
    "cleanup_manifest_files",
    "ServerPromptBuilder",
    "ServerTextExtractor",
]
