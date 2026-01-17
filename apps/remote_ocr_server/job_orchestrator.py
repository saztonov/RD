"""OCR Job orchestration logic.

Extracted from tasks.py for better separation of concerns.
Enables testing without Celery, cleaner error handling.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class OCREngines:
    """Container for OCR backends."""

    strip_backend: Any
    image_backend: Any
    stamp_backend: Any


@dataclass
class JobContext:
    """Context for job execution."""

    job_id: str
    work_dir: Path
    crops_dir: Path
    pdf_path: Optional[Path] = None
    blocks_path: Optional[Path] = None
    blocks: List[Any] = field(default_factory=list)


class JobOrchestrator:
    """
    Orchestrates OCR job execution.

    Separates orchestration logic from Celery task infrastructure.
    Enables testing without Celery, cleaner error handling.
    """

    def __init__(
        self,
        job_id: str,
        on_status_update: Optional[Callable[[str, float, str], None]] = None,
    ):
        """
        Initialize orchestrator.

        Args:
            job_id: Job ID
            on_status_update: Callback for status updates (status, progress, message)
        """
        self.job_id = job_id
        self._on_status_update = on_status_update or self._default_status_update
        self._context: Optional[JobContext] = None

    def _default_status_update(
        self, status: str, progress: float, message: str
    ) -> None:
        """Default status update - writes to database."""
        from .storage import update_job_status

        update_job_status(self.job_id, status, progress=progress, status_message=message)

    def update_status(self, status: str, progress: float, message: str) -> None:
        """Update job status."""
        self._on_status_update(status, progress, message)

    def setup_workspace(self) -> JobContext:
        """Create temporary working directory."""
        work_dir = Path(tempfile.mkdtemp(prefix=f"ocr_job_{self.job_id}_"))
        crops_dir = work_dir / "crops"
        crops_dir.mkdir(exist_ok=True)

        self._context = JobContext(
            job_id=self.job_id,
            work_dir=work_dir,
            crops_dir=crops_dir,
        )
        logger.info(f"Workspace created: {work_dir}")
        return self._context

    @property
    def context(self) -> JobContext:
        """Get current context."""
        if not self._context:
            raise RuntimeError("Workspace not initialized. Call setup_workspace() first.")
        return self._context

    def download_files(self, job) -> tuple[Path, Path]:
        """Download PDF and blocks from R2."""
        from .task_helpers import download_job_files

        self.update_status("processing", 0.06, "Downloading files from R2...")
        pdf_path, blocks_path = download_job_files(job, self.context.work_dir)
        self.context.pdf_path = pdf_path
        self.context.blocks_path = blocks_path
        logger.info(f"Files downloaded: {pdf_path}, {blocks_path}")
        return pdf_path, blocks_path

    def parse_blocks(self) -> List[Any]:
        """Parse blocks from downloaded JSON."""
        from rd_domain.models import Block

        if not self.context.blocks_path:
            raise RuntimeError("Blocks file not downloaded")

        with open(self.context.blocks_path, "r", encoding="utf-8") as f:
            blocks_data = json.load(f)

        # Handle annotation.json format with pages
        if isinstance(blocks_data, dict) and "pages" in blocks_data:
            all_blocks = []
            for page in blocks_data.get("pages", []):
                all_blocks.extend(page.get("blocks", []))
            blocks_data = all_blocks

        blocks = [Block.from_dict(b, migrate_ids=False)[0] for b in blocks_data]
        self.context.blocks = blocks
        logger.info(f"Parsed {len(blocks)} blocks")
        return blocks

    def create_engines(self, job) -> OCREngines:
        """Create OCR engines based on job settings."""
        from rd_pipeline.ocr import create_ocr_engine

        from .redis_rate_limiter import CompatRateLimiter
        from .settings import settings

        job_settings = job.settings
        text_model = (job_settings.text_model if job_settings else "") or ""
        table_model = (job_settings.table_model if job_settings else "") or ""
        image_model = (job_settings.image_model if job_settings else "") or ""
        stamp_model = (job_settings.stamp_model if job_settings else "") or ""

        engine = job.engine or "openrouter"
        job_context = {"job_id": job.id}

        # Strip backend (for TEXT/TABLE blocks)
        if engine == "datalab" and settings.datalab_api_key:
            strip_backend = create_ocr_engine(
                "datalab",
                api_key=settings.datalab_api_key,
                rate_limiter=CompatRateLimiter("datalab", job_context),
                poll_interval=settings.datalab_poll_interval,
                poll_max_attempts=settings.datalab_poll_max_attempts,
                max_retries=settings.datalab_max_retries,
            )
        elif settings.openrouter_api_key:
            strip_model = text_model or table_model or "qwen/qwen3-vl-30b-a3b-instruct"
            strip_backend = create_ocr_engine(
                "openrouter",
                api_key=settings.openrouter_api_key,
                model_name=strip_model,
                rate_limiter=CompatRateLimiter("openrouter", job_context),
            )
        else:
            strip_backend = create_ocr_engine("dummy")

        # Image and stamp backends
        if settings.openrouter_api_key:
            img_model = (
                image_model or text_model or table_model or "qwen/qwen3-vl-30b-a3b-instruct"
            )
            image_backend = create_ocr_engine(
                "openrouter",
                api_key=settings.openrouter_api_key,
                model_name=img_model,
                rate_limiter=CompatRateLimiter("openrouter", job_context),
            )

            stmp_model = (
                stamp_model
                or image_model
                or text_model
                or table_model
                or "qwen/qwen3-vl-30b-a3b-instruct"
            )
            stamp_backend = create_ocr_engine(
                "openrouter",
                api_key=settings.openrouter_api_key,
                model_name=stmp_model,
                rate_limiter=CompatRateLimiter("openrouter", job_context),
            )
        else:
            image_backend = create_ocr_engine("dummy")
            stamp_backend = create_ocr_engine("dummy")

        logger.info(f"OCR engines created for job {job.id}")
        return OCREngines(strip_backend, image_backend, stamp_backend)

    def run_ocr(self, job, engines: OCREngines, start_mem: float) -> None:
        """Execute two-pass OCR."""
        from .task_ocr_twopass import run_two_pass_ocr

        if not self.context.pdf_path or not self.context.blocks:
            raise RuntimeError("PDF or blocks not loaded")

        self.update_status(
            "processing", 0.1, f"Processing: {len(self.context.blocks)} blocks"
        )

        run_two_pass_ocr(
            job,
            self.context.pdf_path,
            self.context.blocks,
            self.context.crops_dir,
            self.context.work_dir,
            engines.strip_backend,
            engines.image_backend,
            engines.stamp_backend,
            start_mem,
        )
        logger.info(f"OCR completed for job {job.id}")

    def generate_and_upload_results(self, job, engines: OCREngines) -> str:
        """Generate results and upload to R2."""
        from .task_results import generate_results
        from .task_upload import upload_results_to_r2

        self.update_status("processing", 0.92, "Generating results...")

        engine = job.engine or "openrouter"
        verification_backend = engines.strip_backend if engine == "datalab" else None

        r2_prefix = generate_results(
            job,
            self.context.pdf_path,
            self.context.blocks,
            self.context.work_dir,
            verification_backend,
        )

        self.update_status("processing", 0.95, "Uploading to cloud...")
        upload_results_to_r2(job, self.context.work_dir, r2_prefix)

        logger.info(f"Results uploaded for job {job.id}")
        return r2_prefix

    def register_node_files(self, job) -> None:
        """Register OCR results in node_files if applicable."""
        if not job.node_id:
            return

        from .node_storage import update_node_pdf_status
        from .storage import register_ocr_results_to_node

        self.update_status("processing", 0.98, "Registering files...")

        registered_count = register_ocr_results_to_node(
            job.node_id, str(job.id), job.document_name, self.context.work_dir
        )
        logger.info(
            f"Registered {registered_count} files in node_files for node {job.node_id}"
        )

        try:
            update_node_pdf_status(job.node_id)
            logger.info(f"PDF status updated for node {job.node_id}")
        except Exception as e:
            logger.warning(f"Failed to update PDF status: {e}")

    def calculate_stats(self) -> Dict[str, int]:
        """Calculate block statistics."""
        blocks = self.context.blocks
        total = len(blocks)
        text_count = sum(1 for b in blocks if b.block_type.value == "text")
        image_blocks = [b for b in blocks if b.block_type.value == "image"]
        stamp_count = sum(
            1 for b in image_blocks if getattr(b, "category_code", None) == "stamp"
        )
        image_count = len(image_blocks) - stamp_count

        return {
            "total": total,
            "text": text_count,
            "image": image_count,
            "stamp": stamp_count,
            "grouped": text_count,
        }

    def cleanup(self) -> None:
        """Clean up temporary directory."""
        if self._context and self._context.work_dir and self._context.work_dir.exists():
            try:
                shutil.rmtree(self._context.work_dir)
                logger.info(f"Workspace cleaned: {self._context.work_dir}")
            except Exception as e:
                logger.warning(f"Error cleaning workspace: {e}")

    def handle_empty_blocks(self, job) -> None:
        """Handle case when there are no blocks to process."""
        from .task_helpers import create_empty_result
        from .task_upload import upload_results_to_r2

        self.update_status("done", 1.0, "No blocks to process")
        create_empty_result(job, self.context.work_dir, self.context.pdf_path)
        upload_results_to_r2(job, self.context.work_dir)
        logger.info(f"Empty result created for job {job.id}")
