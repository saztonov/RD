"""Handler for initializing OCR job with presigned URLs for direct upload."""
import logging
import uuid
from typing import Optional

from fastapi import Form, Header, HTTPException
from pydantic import BaseModel

from apps.remote_ocr_server.queue_checker import check_queue_capacity
from apps.remote_ocr_server.r2_paths import get_doc_prefix, get_pdf_key
from apps.remote_ocr_server.routes.common import check_api_key
from apps.remote_ocr_server.storage import (
    create_job,
    delete_job,
    get_node_pdf_r2_key,
    save_job_settings,
)
from rd_adapters.storage import R2AsyncStorageSync

_logger = logging.getLogger(__name__)

# Presigned URL expiration time (15 minutes)
PRESIGNED_URL_EXPIRATION = 900


class PresignedUrls(BaseModel):
    """Presigned URLs for direct upload."""
    pdf: str
    blocks: str


class InitJobResponse(BaseModel):
    """Response from init endpoint."""
    job_id: str
    presigned_urls: PresignedUrls
    r2_prefix: str


def _get_r2() -> R2AsyncStorageSync:
    """Get R2 storage client."""
    return R2AsyncStorageSync.from_env()


async def init_job_handler(
    client_id: str = Form(...),
    document_id: str = Form(...),
    document_name: str = Form(...),
    task_name: str = Form(""),
    engine: str = Form("openrouter"),
    text_model: str = Form(""),
    table_model: str = Form(""),
    image_model: str = Form(""),
    stamp_model: str = Form(""),
    node_id: str = Form(...),  # node_id теперь обязателен
    pdf_size: int = Form(..., description="PDF file size in bytes"),
    blocks_size: int = Form(..., description="Blocks JSON size in bytes"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Initialize OCR job and return presigned URLs for direct upload.

    This is step 1 of the two-step upload process:
    1. POST /jobs/init - get job_id and presigned URLs
    2. Client uploads files directly to R2 using presigned URLs
    3. POST /jobs/{job_id}/confirm - confirm upload and queue job

    Новая структура R2: n/{node_id}/
        {doc_name}.pdf
        {doc_stem}_result.md
        crops/{block_id}.pdf
    """
    check_api_key(x_api_key)

    # Validate sizes
    max_pdf_size = 500 * 1024 * 1024  # 500 MB
    max_blocks_size = 50 * 1024 * 1024  # 50 MB

    if pdf_size > max_pdf_size:
        raise HTTPException(400, f"PDF too large: {pdf_size / 1024 / 1024:.1f}MB > 500MB")

    if blocks_size > max_blocks_size:
        raise HTTPException(400, f"Blocks file too large: {blocks_size / 1024 / 1024:.1f}MB > 50MB")

    # Check queue capacity
    can_accept, queue_size, max_size = check_queue_capacity()
    if not can_accept:
        raise HTTPException(
            status_code=503,
            detail=f"Queue is full ({queue_size}/{max_size}). Try again later.",
        )

    job_id = str(uuid.uuid4())

    _logger.info(
        f"POST /jobs/init: document_id={document_id[:16]}..., node_id={node_id}"
    )

    # Новая структура путей: n/{node_id}/
    r2_prefix = get_doc_prefix(node_id)

    # Проверяем, есть ли уже PDF в R2
    pdf_r2_key = get_node_pdf_r2_key(node_id)
    pdf_needs_presigned = True

    if pdf_r2_key:
        # PDF уже существует - проверим через head_object в generate_presigned_put_url
        pdf_key = pdf_r2_key
        pdf_needs_presigned = False
    else:
        # Новый PDF - формируем ключ
        pdf_key = get_pdf_key(node_id, document_name)

    blocks_key = f"{r2_prefix}/blocks.json"

    # Create job with pending_upload status
    try:
        job = create_job(
            client_id=client_id,
            document_id=document_id,
            document_name=document_name,
            task_name=task_name,
            engine=engine,
            r2_prefix=r2_prefix,
            status="pending_upload",
            node_id=node_id,
        )

        save_job_settings(job.id, text_model, table_model, image_model, stamp_model)

    except Exception as e:
        _logger.error(f"Failed to create job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create job: {e}")

    # Generate presigned URLs
    try:
        r2 = _get_r2()

        if pdf_needs_presigned:
            pdf_presigned = r2.generate_presigned_put_url(
                pdf_key,
                content_type="application/pdf",
                expiration=PRESIGNED_URL_EXPIRATION,
            )
        else:
            # PDF already exists - return empty URL (client should skip upload)
            pdf_presigned = ""

        blocks_presigned = r2.generate_presigned_put_url(
            blocks_key,
            content_type="application/json",
            expiration=PRESIGNED_URL_EXPIRATION,
        )

        if (pdf_needs_presigned and not pdf_presigned) or not blocks_presigned:
            delete_job(job.id)
            raise HTTPException(500, "Failed to generate presigned URLs")

    except HTTPException:
        raise
    except Exception as e:
        _logger.error(f"Presigned URL generation failed: {e}")
        delete_job(job.id)
        raise HTTPException(500, f"Failed to generate presigned URLs: {e}")

    return {
        "job_id": job.id,
        "presigned_urls": {
            "pdf": pdf_presigned,
            "blocks": blocks_presigned,
        },
        "r2_prefix": r2_prefix,
        "pdf_key": pdf_key,
        "blocks_key": blocks_key,
    }
