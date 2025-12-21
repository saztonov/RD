"""Routes для управления задачами OCR"""
import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Header, UploadFile

from services.remote_ocr.server.storage import (
    add_job_file,
    create_job,
    delete_job,
    delete_job_files,
    get_job,
    get_job_file_by_type,
    get_job_files,
    job_to_dict,
    list_jobs,
    pause_job,
    reset_job_for_restart,
    resume_job,
    save_job_settings,
    update_job_engine,
    update_job_task_name,
)
from services.remote_ocr.server.tasks import run_ocr_task
from services.remote_ocr.server.routes.common import check_api_key, get_r2_storage, get_file_icon

import logging
_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("")
async def create_job_endpoint(
    client_id: str = Form(...),
    document_id: str = Form(...),
    document_name: str = Form(...),
    task_name: str = Form(""),
    engine: str = Form("openrouter"),
    text_model: str = Form(""),
    table_model: str = Form(""),
    image_model: str = Form(""),
    node_id: Optional[str] = Form(None),
    blocks_file: UploadFile = File(..., alias="blocks_file"),
    pdf: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Создать новую задачу OCR"""
    check_api_key(x_api_key)
    
    blocks_json = (await blocks_file.read()).decode("utf-8")
    _logger.info(f"POST /jobs: client_id={client_id}, document_id={document_id[:16]}..., node_id={node_id}")
    
    try:
        blocks_data = json.loads(blocks_json)
    except json.JSONDecodeError as e:
        _logger.error(f"Invalid blocks_json: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid blocks_json: {e}")
    
    job_id = str(uuid.uuid4())
    r2_prefix = f"ocr_jobs/{job_id}"
    
    job = create_job(
        client_id=client_id,
        document_id=document_id,
        document_name=document_name,
        task_name=task_name,
        engine=engine,
        r2_prefix=r2_prefix,
        status="queued",
        node_id=node_id
    )
    
    save_job_settings(job.id, text_model, table_model, image_model)
    
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
        
        blocks_bytes = json.dumps(blocks_data, ensure_ascii=False, indent=2).encode("utf-8")
        blocks_key = f"{r2_prefix}/blocks.json"
        r2.s3_client.put_object(
            Bucket=r2.bucket_name,
            Key=blocks_key,
            Body=blocks_bytes,
            ContentType="application/json"
        )
        add_job_file(job.id, "blocks", blocks_key, "blocks.json", len(blocks_bytes))
        
    except Exception as e:
        _logger.error(f"R2 upload failed: {e}")
        delete_job(job.id)
        raise HTTPException(status_code=500, detail=f"Failed to upload files to R2: {e}")
    
    run_ocr_task.delay(job.id)
    
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "document_id": job.document_id,
        "document_name": job.document_name,
        "task_name": job.task_name
    }


@router.get("")
def list_jobs_endpoint(
    client_id: Optional[str] = None,
    document_id: Optional[str] = None,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> list:
    """Получить список задач"""
    check_api_key(x_api_key)
    
    jobs = list_jobs(client_id, document_id)
    return [
        {
            "id": j.id,
            "status": j.status,
            "progress": j.progress,
            "document_name": j.document_name,
            "task_name": j.task_name,
            "document_id": j.document_id,
            "created_at": j.created_at,
            "updated_at": j.updated_at,
            "error_message": j.error_message
        }
        for j in jobs
    ]


@router.get("/{job_id}")
def get_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить информацию о задаче"""
    check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job_to_dict(job)


@router.get("/{job_id}/details")
def get_job_details_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить детальную информацию о задаче"""
    check_api_key(x_api_key)
    
    job = get_job(job_id, with_files=True, with_settings=True)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = job_to_dict(job)
    
    blocks_file = get_job_file_by_type(job_id, "blocks")
    if blocks_file:
        try:
            r2 = get_r2_storage()
            blocks_text = r2.download_text(blocks_file.r2_key)
            if blocks_text:
                blocks = json.loads(blocks_text)
                
                text_count = sum(1 for b in blocks if b.get("block_type") == "text")
                table_count = sum(1 for b in blocks if b.get("block_type") == "table")
                image_count = sum(1 for b in blocks if b.get("block_type") == "image")
                
                result["block_stats"] = {
                    "total": len(blocks),
                    "text": text_count,
                    "table": table_count,
                    "image": image_count,
                    "grouped": text_count + table_count
                }
        except Exception as e:
            _logger.warning(f"Failed to load blocks from R2: {e}")
    
    if job.settings:
        result["job_settings"] = {
            "text_model": job.settings.text_model,
            "table_model": job.settings.table_model,
            "image_model": job.settings.image_model
        }
    else:
        result["job_settings"] = {}
    
    r2_public_url = os.getenv("R2_PUBLIC_URL")
    if r2_public_url and job.r2_prefix:
        base_url = r2_public_url.rstrip('/')
        result["r2_base_url"] = f"{base_url}/{job.r2_prefix}"
        
        result["r2_files"] = [
            {"name": f.file_name, "path": f.r2_key.replace(f"{job.r2_prefix}/", ""), "icon": get_file_icon(f.file_type)}
            for f in job.files
        ]
    else:
        result["r2_base_url"] = None
        result["r2_files"] = []
    
    return result


@router.get("/{job_id}/result")
def download_result(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить ссылку на результат"""
    check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job not ready, status: {job.status}")
    
    result_file = get_job_file_by_type(job_id, "result_zip")
    if not result_file:
        raise HTTPException(status_code=404, detail="Result file not found")
    
    try:
        r2 = get_r2_storage()
        url = r2.generate_presigned_url(result_file.r2_key, expiration=3600)
        return {"download_url": url, "file_name": result_file.file_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate download URL: {e}")


@router.patch("/{job_id}")
def update_job_endpoint(
    job_id: str,
    task_name: str = Form(...),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Обновить название задачи"""
    check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not update_job_task_name(job_id, task_name):
        raise HTTPException(status_code=500, detail="Failed to update job")
    
    return {"ok": True, "job_id": job_id, "task_name": task_name}


@router.post("/{job_id}/restart")
def restart_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Перезапустить задачу"""
    check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result_files = get_job_files(job_id)
    result_types = ["result_md", "result_zip", "crop"]
    
    try:
        r2 = get_r2_storage()
        for f in result_files:
            if f.file_type in result_types:
                r2.delete_object(f.r2_key)
        
        delete_job_files(job_id, result_types)
    except Exception as e:
        _logger.warning(f"Failed to delete result files from R2: {e}")
    
    if not reset_job_for_restart(job_id):
        raise HTTPException(status_code=500, detail="Failed to reset job")
    
    run_ocr_task.delay(job_id)
    
    return {"ok": True, "job_id": job_id, "status": "queued"}


@router.post("/{job_id}/start")
def start_job_endpoint(
    job_id: str,
    engine: str = Form("openrouter"),
    text_model: str = Form(""),
    table_model: str = Form(""),
    image_model: str = Form(""),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Запустить черновик на распознавание"""
    check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "draft":
        raise HTTPException(status_code=400, detail=f"Job is not a draft, status: {job.status}")
    
    save_job_settings(job_id, text_model, table_model, image_model)
    update_job_engine(job_id, engine)
    
    run_ocr_task.delay(job_id)
    
    return {"ok": True, "job_id": job_id, "status": "queued"}


@router.post("/{job_id}/pause")
def pause_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Поставить задачу на паузу"""
    check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status not in ("queued", "processing"):
        raise HTTPException(status_code=400, detail=f"Cannot pause job in status: {job.status}")
    
    if not pause_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to pause job")
    
    return {"ok": True, "job_id": job_id, "status": "paused"}


@router.post("/{job_id}/resume")
def resume_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Возобновить задачу с паузы"""
    check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "paused":
        raise HTTPException(status_code=400, detail=f"Job is not paused, status: {job.status}")
    
    if not resume_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to resume job")
    
    run_ocr_task.delay(job_id)
    
    return {"ok": True, "job_id": job_id, "status": "queued"}


@router.delete("/{job_id}")
def delete_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Удалить задачу и все связанные файлы"""
    check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.r2_prefix:
        try:
            r2 = get_r2_storage()
            r2_prefix = job.r2_prefix if job.r2_prefix.endswith('/') else f"{job.r2_prefix}/"
            
            files_to_delete = []
            paginator = r2.s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=r2.bucket_name, Prefix=r2_prefix):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        files_to_delete.append({'Key': obj['Key']})
            
            if files_to_delete:
                for i in range(0, len(files_to_delete), 1000):
                    batch = files_to_delete[i:i+1000]
                    r2.s3_client.delete_objects(Bucket=r2.bucket_name, Delete={'Objects': batch})
                _logger.info(f"Deleted {len(files_to_delete)} files from R2 for job {job_id}")
        except Exception as e:
            _logger.warning(f"Failed to delete files from R2: {e}")
    
    if not delete_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to delete job from database")
    
    return {"ok": True, "deleted_job_id": job_id}

