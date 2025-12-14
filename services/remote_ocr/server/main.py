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
    delete_job,
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
    task_name: str = Form(""),
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
    - task_name: название задания
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
        task_name=task_name,
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
        "document_name": job.document_name,
        "task_name": job.task_name
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
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = job_to_dict(job)
    
    # Читаем blocks.json для статистики
    blocks_path = os.path.join(job.job_dir, "blocks.json")
    if os.path.exists(blocks_path):
        with open(blocks_path, "r", encoding="utf-8") as f:
            blocks = json.load(f)
        
        # Подсчитываем блоки по типам
        text_count = 0
        table_count = 0
        image_count = 0
        
        for block in blocks:
            block_type = block.get("block_type", "text")
            if block_type == "text":
                text_count += 1
            elif block_type == "table":
                table_count += 1
            elif block_type == "image":
                image_count += 1
        
        # grouped = текстовые + табличные (объединяются в полосы)
        grouped_count = text_count + table_count
        
        block_stats = {
            "total": len(blocks),
            "text": text_count,
            "table": table_count,
            "image": image_count,
            "grouped": grouped_count
        }
        
        result["block_stats"] = block_stats
    
    # Читаем annotation.json для информации о батчах (если есть)
    annotation_path = os.path.join(job.job_dir, "annotation.json")
    if os.path.exists(annotation_path):
        try:
            with open(annotation_path, "r", encoding="utf-8") as f:
                annotation = json.load(f)
            # Подсчитываем количество страниц как прокси для батчей
            result["num_pages"] = len(annotation.get("pages", []))
        except:
            pass
    
    # Формируем публичный URL для R2 если доступен
    if job.r2_prefix:
        r2_public_url = os.getenv("R2_PUBLIC_URL")  # Публичный URL R2 bucket
        
        if r2_public_url:
            # Убираем trailing slash если есть
            base_url = r2_public_url.rstrip('/')
            result["r2_base_url"] = f"{base_url}/{job.r2_prefix}"
            
            # Формируем список доступных файлов
            result["r2_files"] = [
                {"name": "document.pdf", "path": "document.pdf", "icon": "📄"},
                {"name": "result.md", "path": "result.md", "icon": "📝"},
                {"name": "annotation.json", "path": "annotation.json", "icon": "📋"},
            ]
            
            # Добавляем кропы если есть
            crops_dir = os.path.join(job.job_dir, "crops")
            if os.path.exists(crops_dir):
                crop_files = []
                for f in os.listdir(crops_dir):
                    if f.endswith(('.png', '.jpg', '.jpeg')):
                        crop_files.append({
                            "name": f,
                            "path": f"crops/{f}",
                            "icon": "🖼️"
                        })
                if crop_files:
                    result["r2_files"].extend(sorted(crop_files, key=lambda x: x["name"]))
        else:
            result["r2_base_url"] = None
            result["r2_files"] = []
    else:
        result["r2_base_url"] = None
        result["r2_files"] = []
    
    return result


@app.get("/jobs/{job_id}/result")
def download_result(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> FileResponse:
    """Скачать результат задачи (устарело, используйте R2)"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job not ready, status: {job.status}")
    
    # Файлы удалены после загрузки в R2
    if not job.result_path or not os.path.exists(job.result_path):
        if job.r2_prefix:
            raise HTTPException(
                status_code=404, 
                detail=f"Result files moved to R2 storage. Download from R2 using prefix: {job.r2_prefix}"
            )
        else:
            raise HTTPException(status_code=404, detail="Result file not found")
    
    return FileResponse(
        job.result_path,
        media_type="application/zip",
        filename=f"result_{job_id}.zip"
    )


@app.delete("/jobs/{job_id}")
def delete_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Удалить задачу и её файлы"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Удаляем файлы из job_dir
    import shutil
    if os.path.exists(job.job_dir):
        try:
            shutil.rmtree(job.job_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete job files: {e}")
    
    # Удаляем из БД
    if not delete_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to delete job from database")
    
    return {"ok": True, "deleted_job_id": job_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
