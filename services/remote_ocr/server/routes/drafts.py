"""Routes для работы с черновиками"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Header, UploadFile

from services.remote_ocr.server.storage import create_job, delete_job, add_job_file
from services.remote_ocr.server.routes.common import check_api_key, get_r2_storage

import logging
_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["drafts"])


@router.post("/draft")
async def create_draft_endpoint(
    client_id: str = Form(...),
    document_id: str = Form(...),
    document_name: str = Form(...),
    task_name: str = Form(""),
    annotation_json: str = Form(...),
    pdf: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Создать черновик задачи (без OCR, только сохранение в R2)"""
    check_api_key(x_api_key)
    
    try:
        annotation_data = json.loads(annotation_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid annotation_json: {e}")
    
    job_id = str(uuid.uuid4())
    r2_prefix = f"ocr_jobs/{job_id}"
    
    job = create_job(
        client_id=client_id,
        document_id=document_id,
        document_name=document_name,
        task_name=task_name,
        engine="",
        r2_prefix=r2_prefix,
        status="draft"
    )
    
    try:
        r2 = get_r2_storage()
        
        pdf_content = await pdf.read()
        pdf_key = f"{r2_prefix}/document.pdf"
        r2.s3_client.put_object(
            Bucket=r2.bucket_name,
            Key=pdf_key,
            Body=pdf_content,
            ContentType="application/pdf"
        )
        add_job_file(job.id, "pdf", pdf_key, "document.pdf", len(pdf_content))
        
        annotation_bytes = json.dumps(annotation_data, ensure_ascii=False, indent=2).encode("utf-8")
        annotation_key = f"{r2_prefix}/annotation.json"
        r2.s3_client.put_object(
            Bucket=r2.bucket_name,
            Key=annotation_key,
            Body=annotation_bytes,
            ContentType="application/json"
        )
        add_job_file(job.id, "annotation", annotation_key, "annotation.json", len(annotation_bytes))
        
    except Exception as e:
        _logger.error(f"R2 upload failed for draft: {e}")
        delete_job(job.id)
        raise HTTPException(status_code=500, detail=f"Failed to upload files to R2: {e}")
    
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "document_id": job.document_id,
        "document_name": job.document_name,
        "task_name": job.task_name,
        "r2_prefix": r2_prefix
    }

