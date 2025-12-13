"""FastAPI сервер для удалённого OCR"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Header, UploadFile
from fastapi.responses import FileResponse

from .settings import settings
from .storage import (
    Job,
    create_job,
    get_job,
    init_db,
    job_to_dict,
    list_jobs,
)
from .worker import start_worker, stop_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: инициализация БД и запуск воркера"""
    init_db()
    start_worker()
    yield
    stop_worker()


app = FastAPI(title="rd-remote-ocr", lifespan=lifespan)


def _check_api_key(x_api_key: Optional[str]) -> None:
    """Проверить API ключ если он задан в настройках"""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@app.get("/health")
def health() -> dict:
    """Health check"""
    return {"ok": True}


@app.post("/jobs")
async def create_job_endpoint(
    client_id: str = Form(...),
    document_id: str = Form(...),
    document_name: str = Form(...),
    engine: str = Form("openrouter"),
    blocks_json: str = Form(...),
    pdf: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """
    Создать новую задачу OCR
    
    - client_id: идентификатор клиента
    - document_id: sha256 хеш PDF
    - document_name: имя документа
    - engine: движок OCR
    - blocks_json: JSON со списком блоков
    - pdf: PDF файл
    """
    _check_api_key(x_api_key)
    
    # Парсим блоки
    try:
        blocks_data = json.loads(blocks_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid blocks_json: {e}")
    
    # Создаём директорию для задачи
    import uuid
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(settings.data_dir, "jobs", job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    # Сохраняем PDF
    pdf_path = os.path.join(job_dir, "document.pdf")
    content = await pdf.read()
    with open(pdf_path, "wb") as f:
        f.write(content)
    
    # Сохраняем blocks.json
    blocks_path = os.path.join(job_dir, "blocks.json")
    with open(blocks_path, "w", encoding="utf-8") as f:
        json.dump(blocks_data, f, ensure_ascii=False, indent=2)
    
    # Создаём запись в БД
    job = create_job(
        client_id=client_id,
        document_id=document_id,
        document_name=document_name,
        engine=engine,
        job_dir=job_dir
    )
    # Переназначаем id (create_job генерирует свой)
    # В нашей реализации это не нужно, т.к. job_dir уже содержит правильный id
    
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "document_id": job.document_id,
        "document_name": job.document_name
    }


@app.get("/jobs")
def list_jobs_endpoint(
    client_id: str,
    document_id: Optional[str] = None,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> list:
    """Получить список задач по client_id и опционально document_id"""
    _check_api_key(x_api_key)
    
    jobs = list_jobs(client_id, document_id)
    return [
        {
            "id": j.id,
            "status": j.status,
            "progress": j.progress,
            "document_name": j.document_name,
            "document_id": j.document_id,
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


@app.get("/jobs/{job_id}/result")
def download_result(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> FileResponse:
    """Скачать результат задачи (zip)"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job not ready, status: {job.status}")
    
    if not job.result_path or not os.path.exists(job.result_path):
        raise HTTPException(status_code=404, detail="Result file not found")
    
    return FileResponse(
        job.result_path,
        media_type="application/zip",
        filename=f"result_{job_id}.zip"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
