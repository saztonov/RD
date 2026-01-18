"""Handler for confirming direct upload and queueing OCR job."""
import logging
from typing import Optional

from fastapi import Header, HTTPException, Path

from apps.remote_ocr_server.r2_paths import get_doc_prefix, get_pdf_key
from apps.remote_ocr_server.routes.common import check_api_key
from apps.remote_ocr_server.storage import (
    add_job_file,
    add_node_file,
    get_job,
    get_node_pdf_r2_key,
    update_job_status,
    update_node_r2_key,
)
from apps.remote_ocr_server.tasks import run_ocr_task
from rd_adapters.storage import R2AsyncStorageSync

_logger = logging.getLogger(__name__)


def _get_r2() -> R2AsyncStorageSync:
    """Get R2 storage client."""
    return R2AsyncStorageSync.from_env()


async def confirm_job_handler(
    job_id: str = Path(..., description="Job ID from init endpoint"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Confirm that files have been uploaded and queue the OCR job.

    This is step 2 of the two-step upload process:
    1. POST /jobs/init - get job_id and presigned URLs
    2. Client uploads files directly to R2 using presigned URLs
    3. POST /jobs/{job_id}/confirm - confirm upload and queue job

    The endpoint verifies that:
    - Job exists with status "pending_upload"
    - PDF file exists in R2
    - Blocks file exists in R2

    Then:
    - Registers files in job_files table
    - Updates job status to "queued"
    - Queues the Celery task
    """
    check_api_key(x_api_key)

    # Get job
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if job.status != "pending_upload":
        raise HTTPException(
            400,
            f"Job is not pending upload. Current status: {job.status}"
        )

    _logger.info(f"POST /jobs/{job_id}/confirm: verifying uploads...")

    # node_id обязателен
    if not job.node_id:
        raise HTTPException(400, "node_id is required for OCR job")

    r2 = _get_r2()

    # Новая структура путей: n/{node_id}/
    r2_prefix = get_doc_prefix(job.node_id)

    # PDF ключ: проверяем существующий или формируем новый
    pdf_r2_key = get_node_pdf_r2_key(job.node_id)
    if not pdf_r2_key:
        pdf_r2_key = get_pdf_key(job.node_id, job.document_name)

    # blocks.json в папке документа
    blocks_r2_key = f"{r2_prefix}/blocks.json"

    # Verify files exist in R2
    pdf_exists = r2.exists(pdf_r2_key)
    if not pdf_exists:
        _logger.error(f"PDF not found in R2: {pdf_r2_key}")
        raise HTTPException(400, f"PDF not uploaded: {pdf_r2_key}")

    blocks_exists = r2.exists(blocks_r2_key)
    if not blocks_exists:
        _logger.error(f"Blocks not found in R2: {blocks_r2_key}")
        raise HTTPException(400, f"Blocks file not uploaded: {blocks_r2_key}")

    # Register files in database
    try:
        # Register in node_files if new PDF
        existing_pdf_key = get_node_pdf_r2_key(job.node_id)
        if not existing_pdf_key:
            add_node_file(
                job.node_id,
                "pdf",
                pdf_r2_key,
                job.document_name,
                0,  # Size unknown from direct upload
                "application/pdf",
            )
            update_node_r2_key(job.node_id, pdf_r2_key)

        # Register files in job_files
        add_job_file(job.id, "blocks", blocks_r2_key, "blocks.json", 0)
        add_job_file(job.id, "pdf", pdf_r2_key, job.document_name, 0)

    except Exception as e:
        _logger.error(f"Failed to register files: {e}")
        # Don't delete job - files are uploaded, just registration failed
        raise HTTPException(500, f"Failed to register files: {e}")

    # Update status and queue task
    try:
        update_job_status(job_id, "queued", progress=0.0, status_message="Queued")
        run_ocr_task.delay(job_id)
        _logger.info(f"Job {job_id} confirmed and queued")

    except Exception as e:
        _logger.error(f"Failed to queue job: {e}")
        raise HTTPException(500, f"Failed to queue job: {e}")

    return {
        "id": job.id,
        "status": "queued",
        "progress": 0.0,
        "document_id": job.document_id,
        "document_name": job.document_name,
        "task_name": job.task_name,
    }
