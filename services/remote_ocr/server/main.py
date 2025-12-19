"""FastAPI сервер для удалённого OCR"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Header, UploadFile, Request
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
    pause_job,
    reset_job_for_restart,
    resume_job,
    update_job_status,
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

import logging
_logger = logging.getLogger(__name__)

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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
    """
    Создать черновик задачи (без OCR, только сохранение)
    
    - client_id: идентификатор клиента
    - document_id: sha256 хеш PDF
    - document_name: имя документа
    - task_name: название задания
    - annotation_json: JSON с разметкой (Document)
    - pdf: PDF файл
    """
    _check_api_key(x_api_key)
    
    # Парсим аннотацию
    try:
        annotation_data = json.loads(annotation_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid annotation_json: {e}")
    
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
    
    # Сохраняем annotation.json
    annotation_path = os.path.join(job_dir, "annotation.json")
    with open(annotation_path, "w", encoding="utf-8") as f:
        json.dump(annotation_data, f, ensure_ascii=False, indent=2)
    
    # Создаём запись в БД со статусом draft
    job = create_job(
        client_id=client_id,
        document_id=document_id,
        document_name=document_name,
        task_name=task_name,
        engine="",
        job_dir=job_dir,
        status="draft"
    )
    
    # Загружаем в R2 если настроено
    r2_prefix = None
    try:
        from rd_core.r2_storage import R2Storage
        r2 = R2Storage()
        r2_prefix = f"ocr_results/{job.id}"
        
        # Загружаем PDF и annotation.json
        r2.upload_file(pdf_path, f"{r2_prefix}/document.pdf")
        r2.upload_file(annotation_path, f"{r2_prefix}/annotation.json")
        
        # Обновляем r2_prefix в БД
        from .storage import update_job_status
        update_job_status(job.id, "draft", r2_prefix=r2_prefix)
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"R2 upload failed for draft: {e}")
    
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
    
    # Парсим блоки из файла
    blocks_json = (await blocks_file.read()).decode("utf-8")
    _logger.info(f"POST /jobs: client_id={client_id}, document_id={document_id[:16]}..., blocks_json length={len(blocks_json)}")
    try:
        blocks_data = json.loads(blocks_json)
    except json.JSONDecodeError as e:
        _logger.error(f"Invalid blocks_json: {e}, first 500 chars: {blocks_json[:500]}")
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

    # Сохраняем настройки задачи (модели по типам блоков)
    settings_path = os.path.join(job_dir, "job_settings.json")
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "text_model": text_model,
                "table_model": table_model,
                "image_model": image_model,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    
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
    client_id: Optional[str] = None,
    document_id: Optional[str] = None,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> list:
    """Получить список задач. Без client_id возвращает все задачи."""
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
    
    # Читаем job_settings.json
    job_settings_path = os.path.join(job.job_dir, "job_settings.json")
    if os.path.exists(job_settings_path):
        try:
            with open(job_settings_path, "r", encoding="utf-8") as f:
                result["job_settings"] = json.load(f)
        except:
            result["job_settings"] = {}
    else:
        result["job_settings"] = {}
    
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
            
            # Добавляем папку crops как элемент-директорию если есть файлы
            crops_dir = os.path.join(job.job_dir, "crops")
            if os.path.exists(crops_dir):
                crop_files = []
                for f in os.listdir(crops_dir):
                    if f.endswith(('.png', '.jpg', '.jpeg', '.pdf')):
                        crop_files.append({
                            "name": f,
                            "path": f"crops/{f}",
                            "icon": "🖼️" if not f.endswith('.pdf') else "📄"
                        })
                if crop_files:
                    # Добавляем папку crops как навигационный элемент
                    result["r2_files"].append({
                        "name": "crops/",
                        "path": "crops",
                        "icon": "📁",
                        "is_dir": True,
                        "children": sorted(crop_files, key=lambda x: x["name"])
                    })
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


@app.post("/jobs/{job_id}/restart")
def restart_job_endpoint(
    job_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Перезапустить задачу (удаляет результаты, сбрасывает статус в queued)"""
    _check_api_key(x_api_key)
    
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Удаляем результаты из job_dir (annotation.json, result.md, crops/)
    import shutil
    for fname in ["annotation.json", "result.md", "result.zip"]:
        fpath = os.path.join(job.job_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    
    crops_dir = os.path.join(job.job_dir, "crops")
    if os.path.exists(crops_dir):
        try:
            shutil.rmtree(crops_dir)
            os.makedirs(crops_dir)
        except Exception:
            pass
    
    # Сбрасываем статус задачи
    if not reset_job_for_restart(job_id):
        raise HTTPException(status_code=500, detail="Failed to reset job")
    
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
    
    # Обновляем job_settings.json
    settings_path = os.path.join(job.job_dir, "job_settings.json")
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump({
            "text_model": text_model,
            "table_model": table_model,
            "image_model": image_model,
        }, f, ensure_ascii=False, indent=2)
    
    # Обновляем engine в БД и меняем статус на queued
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    from .storage import _db_lock, _get_connection
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE jobs SET status = 'queued', engine = ?, updated_at = ? WHERE id = ?",
                (engine, now, job_id)
            )
            conn.commit()
        finally:
            conn.close()
    
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
    
    return {"ok": True, "job_id": job_id, "status": "queued"}


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
