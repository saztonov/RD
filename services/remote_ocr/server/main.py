"""FastAPI сервер для удалённого OCR (все данные через Supabase + R2)"""
from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Header, UploadFile, Request
from fastapi.responses import JSONResponse

from .settings import settings
from .storage import (
    Job,
    JobSettings,
    add_job_file,
    create_job,
    delete_job,
    delete_job_files,
    get_job,
    get_job_file_by_type,
    get_job_files,
    get_job_settings,
    init_db,
    job_to_dict,
    list_jobs,
    pause_job,
    reset_job_for_restart,
    resume_job,
    save_job_settings,
    update_job_engine,
    update_job_status,
    update_job_task_name,
)
from .tasks import run_ocr_task

import logging
_logger = logging.getLogger(__name__)


def _get_r2_storage():
    """Получить R2 Storage клиент"""
    from rd_core.r2_storage import R2Storage
    return R2Storage()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: инициализация БД (воркер запускается отдельно через Celery)"""
    init_db()
    yield


app = FastAPI(title="rd-remote-ocr", lifespan=lifespan)


from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware


class LogRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and "/jobs" in str(request.url.path):
            content_type = request.headers.get("content-type", "")
            _logger.info(f"POST /jobs Content-Type: {content_type}")
        try:
            response = await call_next(request)
            if response.status_code >= 400:
                _logger.error(f"{request.method} {request.url.path} -> {response.status_code}")
            return response
        except Exception as e:
            _logger.exception(f"Exception in {request.method} {request.url.path}: {e}")
            raise


app.add_middleware(LogRequestMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    _logger.error(f"Validation error on {request.method} {request.url.path}: {exc.errors()}")
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


def _check_api_key(x_api_key: Optional[str]) -> None:
    """Проверить API ключ если он задан в настройках"""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@app.get("/health")
def health() -> dict:
    """Health check"""
    return {"ok": True}


@app.post("/jobs/draft")
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
    _check_api_key(x_api_key)
    
    try:
        annotation_data = json.loads(annotation_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid annotation_json: {e}")
    
    job_id = str(uuid.uuid4())
    r2_prefix = f"ocr_jobs/{job_id}"
    
    # Создаём запись в БД
    job = create_job(
        client_id=client_id,
        document_id=document_id,
        document_name=document_name,
        task_name=task_name,
        engine="",
        r2_prefix=r2_prefix,
        status="draft"
    )
    
    # Загружаем файлы в R2
    try:
        r2 = _get_r2_storage()
        
        # PDF
        pdf_content = await pdf.read()
        pdf_key = f"{r2_prefix}/document.pdf"
        r2.s3_client.put_object(
            Bucket=r2.bucket_name,
            Key=pdf_key,
            Body=pdf_content,
            ContentType="application/pdf"
        )
        add_job_file(job.id, "pdf", pdf_key, "document.pdf", len(pdf_content))
        
        # Annotation JSON
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


@app.post("/jobs")
async def create_job_endpoint(
    client_id: str = Form(...),
    document_id: str = Form(...),
    document_name: str = Form(...),
    task_name: str = Form(""),
    engine: str = Form("openrouter"),
    text_model: str = Form(""),
    table_model: str = Form(""),
    image_model: str = Form(""),
    blocks_file: UploadFile = File(..., alias="blocks_file"),
    pdf: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Создать новую задачу OCR (файлы сохраняются в R2)"""
    _check_api_key(x_api_key)
    
    blocks_json = (await blocks_file.read()).decode("utf-8")
    _logger.info(f"POST /jobs: client_id={client_id}, document_id={document_id[:16]}...")
    
    try:
        blocks_data = json.loads(blocks_json)
    except json.JSONDecodeError as e:
        _logger.error(f"Invalid blocks_json: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid blocks_json: {e}")
    
    job_id = str(uuid.uuid4())
    r2_prefix = f"ocr_jobs/{job_id}"
    
    # Создаём запись в БД
    job = create_job(
        client_id=client_id,
        document_id=document_id,
        document_name=document_name,
        task_name=task_name,
        engine=engine,
        r2_prefix=r2_prefix,
        status="queued"
    )
    
    # Сохраняем настройки
    save_job_settings(job.id, text_model, table_model, image_model)
    
    # Загружаем файлы в R2
    try:
        r2 = _get_r2_storage()
        
        # PDF
        pdf_content = await pdf.read()
        pdf_key = f"{r2_prefix}/document.pdf"
        r2.s3_client.put_object(
            Bucket=r2.bucket_name,
            Key=pdf_key,
            Body=pdf_content,
            ContentType="application/pdf"
        )
        add_job_file(job.id, "pdf", pdf_key, "document.pdf", len(pdf_content))
        
        # Blocks JSON
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
    
    # Отправляем задачу в очередь Celery
    run_ocr_task.delay(job.id)
    
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "document_id": job.document_id,
        "document_name": job.document_name,
        "task_name": job.task_name
    }


@app.get("/jobs")
def list_jobs_endpoint(
    client_id: Optional[str] = None,
    document_id: Optional[str] = None,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> list:
    """Получить список задач"""
    _check_api_key(x_api_key)
    
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


@app.get("/jobs/{job_id}")
def get_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить информацию о задаче"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job_to_dict(job)


@app.get("/jobs/{job_id}/details")
def get_job_details_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить детальную информацию о задаче"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id, with_files=True, with_settings=True)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = job_to_dict(job)
    
    # Читаем blocks.json из R2 для статистики
    blocks_file = get_job_file_by_type(job_id, "blocks")
    if blocks_file:
        try:
            r2 = _get_r2_storage()
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
    
    # Настройки задачи
    if job.settings:
        result["job_settings"] = {
            "text_model": job.settings.text_model,
            "table_model": job.settings.table_model,
            "image_model": job.settings.image_model
        }
    else:
        result["job_settings"] = {}
    
    # Формируем публичный URL для R2
    r2_public_url = os.getenv("R2_PUBLIC_URL")
    if r2_public_url and job.r2_prefix:
        base_url = r2_public_url.rstrip('/')
        result["r2_base_url"] = f"{base_url}/{job.r2_prefix}"
        
        # Список файлов из БД
        result["r2_files"] = [
            {"name": f.file_name, "path": f.r2_key.replace(f"{job.r2_prefix}/", ""), "icon": _get_file_icon(f.file_type)}
            for f in job.files
        ]
    else:
        result["r2_base_url"] = None
        result["r2_files"] = []
    
    return result


def _get_file_icon(file_type: str) -> str:
    icons = {
        "pdf": "📄",
        "blocks": "📋",
        "annotation": "📋",
        "result_md": "📝",
        "result_zip": "📦",
        "crop": "🖼️"
    }
    return icons.get(file_type, "📄")


@app.get("/jobs/{job_id}/result")
def download_result(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Получить ссылку на результат (скачивание через R2)"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job not ready, status: {job.status}")
    
    result_file = get_job_file_by_type(job_id, "result_zip")
    if not result_file:
        raise HTTPException(status_code=404, detail="Result file not found")
    
    # Генерируем presigned URL
    try:
        r2 = _get_r2_storage()
        url = r2.generate_presigned_url(result_file.r2_key, expiration=3600)
        return {"download_url": url, "file_name": result_file.file_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate download URL: {e}")


@app.patch("/jobs/{job_id}")
def update_job_endpoint(
    job_id: str,
    task_name: str = Form(...),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Обновить название задачи"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not update_job_task_name(job_id, task_name):
        raise HTTPException(status_code=500, detail="Failed to update job")
    
    return {"ok": True, "job_id": job_id, "task_name": task_name}


@app.post("/jobs/{job_id}/restart")
def restart_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Перезапустить задачу"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Удаляем результаты из R2
    result_files = get_job_files(job_id)
    result_types = ["result_md", "result_zip", "crop"]
    
    try:
        r2 = _get_r2_storage()
        for f in result_files:
            if f.file_type in result_types:
                r2.delete_object(f.r2_key)
        
        # Удаляем записи из БД
        delete_job_files(job_id, result_types)
    except Exception as e:
        _logger.warning(f"Failed to delete result files from R2: {e}")
    
    if not reset_job_for_restart(job_id):
        raise HTTPException(status_code=500, detail="Failed to reset job")
    
    # Отправляем задачу в очередь Celery
    run_ocr_task.delay(job_id)
    
    return {"ok": True, "job_id": job_id, "status": "queued"}


@app.post("/jobs/{job_id}/start")
def start_job_endpoint(
    job_id: str,
    engine: str = Form("openrouter"),
    text_model: str = Form(""),
    table_model: str = Form(""),
    image_model: str = Form(""),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Запустить черновик на распознавание"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "draft":
        raise HTTPException(status_code=400, detail=f"Job is not a draft, status: {job.status}")
    
    # Сохраняем настройки в Supabase
    save_job_settings(job_id, text_model, table_model, image_model)
    
    # Обновляем engine и статус
    update_job_engine(job_id, engine)
    
    # Отправляем задачу в очередь Celery
    run_ocr_task.delay(job_id)
    
    return {"ok": True, "job_id": job_id, "status": "queued"}


@app.post("/jobs/{job_id}/pause")
def pause_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Поставить задачу на паузу"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status not in ("queued", "processing"):
        raise HTTPException(status_code=400, detail=f"Cannot pause job in status: {job.status}")
    
    if not pause_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to pause job")
    
    return {"ok": True, "job_id": job_id, "status": "paused"}


@app.post("/jobs/{job_id}/resume")
def resume_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Возобновить задачу с паузы"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "paused":
        raise HTTPException(status_code=400, detail=f"Job is not paused, status: {job.status}")
    
    if not resume_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to resume job")
    
    # Отправляем задачу в очередь Celery
    run_ocr_task.delay(job_id)
    
    return {"ok": True, "job_id": job_id, "status": "queued"}


@app.delete("/jobs/{job_id}")
def delete_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Удалить задачу и все связанные файлы (R2 + Supabase)"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Удаляем ВСЕ файлы из R2 по префиксу
    if job.r2_prefix:
        try:
            r2 = _get_r2_storage()
            r2_prefix = job.r2_prefix if job.r2_prefix.endswith('/') else f"{job.r2_prefix}/"
            
            # Используем paginator для полного списка
            files_to_delete = []
            paginator = r2.s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=r2.bucket_name, Prefix=r2_prefix):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        files_to_delete.append({'Key': obj['Key']})
            
            # Удаляем пакетами по 1000
            if files_to_delete:
                for i in range(0, len(files_to_delete), 1000):
                    batch = files_to_delete[i:i+1000]
                    r2.s3_client.delete_objects(Bucket=r2.bucket_name, Delete={'Objects': batch})
                _logger.info(f"Deleted {len(files_to_delete)} files from R2 for job {job_id}")
        except Exception as e:
            _logger.warning(f"Failed to delete files from R2: {e}")
    
    # Удаляем из БД (каскадно удалит job_files и job_settings)
    if not delete_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to delete job from database")
    
    return {"ok": True, "deleted_job_id": job_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
