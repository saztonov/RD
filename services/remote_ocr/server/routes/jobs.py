"""Routes для управления задачами OCR"""
import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from services.remote_ocr.server.queue_checker import check_queue_capacity
from services.remote_ocr.server.routes.common import (
    check_api_key,
    get_file_icon,
    get_r2_storage,
    get_r2_sync_client,
)
from services.remote_ocr.server.storage import (
    add_job_file,
    add_node_file,
    create_job,
    delete_job,
    delete_job_files,
    get_job,
    get_job_file_by_type,
    get_job_files,
    get_node_info,
    get_node_pdf_r2_key,
    job_to_dict,
    list_jobs,
    pause_job,
    reset_job_for_restart,
    resume_job,
    save_job_settings,
    update_job_engine,
    update_job_task_name,
    update_node_r2_key,
)
from services.remote_ocr.server.tasks import run_ocr_task

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
    stamp_model: str = Form(""),
    node_id: Optional[str] = Form(None),
    blocks_file: UploadFile = File(..., alias="blocks_file"),
    pdf: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Создать новую задачу OCR.

    Если node_id указан - файлы берутся из tree_docs/{node_id}/, не дублируем.
    """
    check_api_key(x_api_key)

    blocks_json = (await blocks_file.read()).decode("utf-8")
    _logger.info(
        f"POST /jobs: client_id={client_id}, document_id={document_id[:16]}..., node_id={node_id}"
    )

    try:
        blocks_data = json.loads(blocks_json)
    except json.JSONDecodeError as e:
        _logger.error(f"Invalid blocks_json: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid blocks_json: {e}")

    job_id = str(uuid.uuid4())

    # Определяем r2_prefix - папку для файлов задачи
    # Для node_id берём папку где лежит PDF (из node_files/attributes)
    # Для остальных - ocr_jobs/{job_id}
    pdf_needs_upload = False  # Флаг: нужно ли загрузить PDF в R2

    if node_id:
        pdf_r2_key = get_node_pdf_r2_key(node_id)
        if pdf_r2_key:
            from pathlib import PurePosixPath

            # Проверяем существование PDF в R2
            try:
                s3_check, bucket_check = get_r2_sync_client()
                s3_check.head_object(Bucket=bucket_check, Key=pdf_r2_key)
            except Exception:
                # PDF не существует в R2 - нужно загрузить
                _logger.warning(f"PDF not found in R2, will upload: {pdf_r2_key}")
                pdf_needs_upload = True
            r2_prefix = str(PurePosixPath(pdf_r2_key).parent)
        else:
            # Нет r2_key - формируем на основе parent_id
            node_info = get_node_info(node_id)
            if node_info and node_info.get("parent_id"):
                r2_prefix = f"tree_docs/{node_info['parent_id']}"
            else:
                r2_prefix = f"tree_docs/{node_id}"
            pdf_r2_key = f"{r2_prefix}/{document_name}"
            pdf_needs_upload = True
    else:
        r2_prefix = f"ocr_jobs/{job_id}"

    job = create_job(
        client_id=client_id,
        document_id=document_id,
        document_name=document_name,
        task_name=task_name,
        engine=engine,
        r2_prefix=r2_prefix,
        status="queued",
        node_id=node_id,
    )

    save_job_settings(job.id, text_model, table_model, image_model, stamp_model)

    # Backpressure: проверяем размер очереди
    can_accept, queue_size, max_size = check_queue_capacity()
    if not can_accept:
        raise HTTPException(
            status_code=503,
            detail=f"Queue is full ({queue_size}/{max_size}). Try again later.",
        )

    try:
        s3_client, bucket_name = get_r2_sync_client()

        if node_id:
            from pathlib import PurePosixPath

            doc_stem = PurePosixPath(document_name).stem

            # Если PDF нет в R2 - загружаем и регистрируем
            if pdf_needs_upload:
                pdf_content = await pdf.read()
                pdf_key = pdf_r2_key or f"{r2_prefix}/{document_name}"
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=pdf_key,
                    Body=pdf_content,
                    ContentType="application/pdf",
                )
                _logger.info(
                    f"Uploaded PDF to R2: {pdf_key} ({len(pdf_content)} bytes)"
                )

                # Регистрируем в node_files
                add_node_file(
                    node_id,
                    "pdf",
                    pdf_key,
                    document_name,
                    len(pdf_content),
                    "application/pdf",
                )
                # Обновляем attributes.r2_key в tree_nodes
                update_node_r2_key(node_id, pdf_key)
            else:
                pdf_key = pdf_r2_key

            # Формируем annotation.json с именем документа: {doc_stem}_annotation.json
            blocks_bytes = json.dumps(blocks_data, ensure_ascii=False, indent=2).encode(
                "utf-8"
            )
            blocks_key = f"{r2_prefix}/{doc_stem}_annotation.json"
            s3_client.put_object(
                Bucket=bucket_name,
                Key=blocks_key,
                Body=blocks_bytes,
                ContentType="application/json",
            )
            add_job_file(
                job.id,
                "blocks",
                blocks_key,
                f"{doc_stem}_annotation.json",
                len(blocks_bytes),
            )
            add_job_file(job.id, "pdf", pdf_key, document_name, 0)
        else:
            # Загружаем файлы в ocr_jobs (обратная совместимость)
            pdf_content = await pdf.read()
            pdf_key = f"{r2_prefix}/document.pdf"
            s3_client.put_object(
                Bucket=bucket_name,
                Key=pdf_key,
                Body=pdf_content,
                ContentType="application/pdf",
            )
            add_job_file(job.id, "pdf", pdf_key, "document.pdf", len(pdf_content))

            blocks_bytes = json.dumps(blocks_data, ensure_ascii=False, indent=2).encode(
                "utf-8"
            )
            blocks_key = f"{r2_prefix}/blocks.json"
            s3_client.put_object(
                Bucket=bucket_name,
                Key=blocks_key,
                Body=blocks_bytes,
                ContentType="application/json",
            )
            add_job_file(job.id, "blocks", blocks_key, "blocks.json", len(blocks_bytes))

    except Exception as e:
        _logger.error(f"R2 upload failed: {e}")
        delete_job(job.id)
        raise HTTPException(
            status_code=500, detail=f"Failed to upload files to R2: {e}"
        )

    run_ocr_task.delay(job.id)

    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "document_id": job.document_id,
        "document_name": job.document_name,
        "task_name": job.task_name,
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
            "error_message": j.error_message,
            "node_id": j.node_id,
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
                    "grouped": text_count + table_count,
                }
        except Exception as e:
            _logger.warning(f"Failed to load blocks from R2: {e}")

    if job.settings:
        result["job_settings"] = {
            "text_model": job.settings.text_model,
            "table_model": job.settings.table_model,
            "image_model": job.settings.image_model,
            "stamp_model": job.settings.stamp_model,
        }
    else:
        result["job_settings"] = {}

    r2_public_url = os.getenv("R2_PUBLIC_URL")
    if r2_public_url and job.r2_prefix:
        base_url = r2_public_url.rstrip("/")
        result["r2_base_url"] = f"{base_url}/{job.r2_prefix}"

        result["r2_files"] = [
            {
                "name": f.file_name,
                "path": f.r2_key.replace(f"{job.r2_prefix}/", ""),
                "icon": get_file_icon(f.file_type),
            }
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
        raise HTTPException(
            status_code=400, detail=f"Job not ready, status: {job.status}"
        )

    result_file = get_job_file_by_type(job_id, "result_zip")
    if not result_file:
        raise HTTPException(status_code=404, detail="Result file not found")

    try:
        r2 = get_r2_storage()
        url = r2.generate_presigned_url(result_file.r2_key, expiration=3600)
        return {"download_url": url, "file_name": result_file.file_name}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate download URL: {e}"
        )


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
async def restart_job_endpoint(
    job_id: str,
    blocks_file: Optional[UploadFile] = File(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Перезапустить задачу. Опционально обновить блоки."""
    check_api_key(x_api_key)

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    result_files = get_job_files(job_id)
    result_types = ["result_md", "result_zip", "crop"]

    try:
        s3_client, bucket_name = get_r2_sync_client()

        # Собираем ключи для пакетного удаления
        keys_to_delete = [f.r2_key for f in result_files if f.file_type in result_types]

        if keys_to_delete:
            # Пакетное удаление (до 1000 файлов за раз)
            for i in range(0, len(keys_to_delete), 1000):
                batch = keys_to_delete[i : i + 1000]
                delete_dict = {"Objects": [{"Key": key} for key in batch]}
                s3_client.delete_objects(Bucket=bucket_name, Delete=delete_dict)
            _logger.info(
                f"Deleted {len(keys_to_delete)} result files from R2 for job {job_id}"
            )

        delete_job_files(job_id, result_types)
    except Exception as e:
        _logger.warning(f"Failed to delete result files from R2: {e}")

    # Обновить блоки если переданы
    if blocks_file:
        try:
            blocks_json = (await blocks_file.read()).decode("utf-8")
            blocks_data = json.loads(blocks_json)
            blocks_bytes = json.dumps(blocks_data, ensure_ascii=False, indent=2).encode(
                "utf-8"
            )

            s3_client, bucket_name = get_r2_sync_client()

            # Определяем правильный r2_prefix для node_id
            if job.node_id:
                pdf_r2_key = get_node_pdf_r2_key(job.node_id)
                if pdf_r2_key:
                    from pathlib import PurePosixPath

                    r2_prefix = str(PurePosixPath(pdf_r2_key).parent)
                    doc_stem = PurePosixPath(job.document_name).stem
                    blocks_key = f"{r2_prefix}/{doc_stem}_annotation.json"
                else:
                    blocks_key = f"{job.r2_prefix}/annotation.json"
            else:
                blocks_key = f"{job.r2_prefix}/annotation.json"

            s3_client.put_object(
                Bucket=bucket_name,
                Key=blocks_key,
                Body=blocks_bytes,
                ContentType="application/json",
            )
            _logger.info(f"Updated blocks for job {job_id}: {blocks_key}")
        except Exception as e:
            _logger.error(f"Failed to update blocks: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid blocks: {e}")

    if not reset_job_for_restart(job_id):
        raise HTTPException(status_code=500, detail="Failed to reset job")

    # Backpressure
    can_accept, queue_size, max_size = check_queue_capacity()
    if not can_accept:
        raise HTTPException(
            status_code=503, detail=f"Queue full ({queue_size}/{max_size})"
        )

    run_ocr_task.delay(job_id)

    return {"ok": True, "job_id": job_id, "status": "queued"}


@router.post("/{job_id}/start")
def start_job_endpoint(
    job_id: str,
    engine: str = Form("openrouter"),
    text_model: str = Form(""),
    table_model: str = Form(""),
    image_model: str = Form(""),
    stamp_model: str = Form(""),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Запустить черновик на распознавание"""
    check_api_key(x_api_key)

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "draft":
        raise HTTPException(
            status_code=400, detail=f"Job is not a draft, status: {job.status}"
        )

    save_job_settings(job_id, text_model, table_model, image_model, stamp_model)
    update_job_engine(job_id, engine)

    # Backpressure
    can_accept, queue_size, max_size = check_queue_capacity()
    if not can_accept:
        raise HTTPException(
            status_code=503, detail=f"Queue full ({queue_size}/{max_size})"
        )

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
        raise HTTPException(
            status_code=400, detail=f"Cannot pause job in status: {job.status}"
        )

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
        raise HTTPException(
            status_code=400, detail=f"Job is not paused, status: {job.status}"
        )

    if not resume_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to resume job")

    # Backpressure
    can_accept, queue_size, max_size = check_queue_capacity()
    if not can_accept:
        raise HTTPException(
            status_code=503, detail=f"Queue full ({queue_size}/{max_size})"
        )

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
            s3_client, bucket_name = get_r2_sync_client()
            r2_prefix = (
                job.r2_prefix if job.r2_prefix.endswith("/") else f"{job.r2_prefix}/"
            )

            files_to_delete = []
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket_name, Prefix=r2_prefix):
                if "Contents" in page:
                    for obj in page["Contents"]:
                        files_to_delete.append({"Key": obj["Key"]})

            if files_to_delete:
                for i in range(0, len(files_to_delete), 1000):
                    batch = files_to_delete[i : i + 1000]
                    s3_client.delete_objects(
                        Bucket=bucket_name, Delete={"Objects": batch}
                    )
                _logger.info(
                    f"Deleted {len(files_to_delete)} files from R2 for job {job_id}"
                )
        except Exception as e:
            _logger.warning(f"Failed to delete files from R2: {e}")

    if not delete_job(job_id):
        raise HTTPException(
            status_code=500, detail="Failed to delete job from database"
        )

    return {"ok": True, "deleted_job_id": job_id}
