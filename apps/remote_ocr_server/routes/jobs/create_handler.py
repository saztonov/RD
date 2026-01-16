"""Обработчик создания задачи OCR"""
import json
import logging
import uuid
from typing import Optional

from fastapi import File, Form, Header, HTTPException, UploadFile

from apps.remote_ocr_server.queue_checker import check_queue_capacity
from apps.remote_ocr_server.routes.common import (
    check_api_key,
    get_r2_sync_client,
)
from apps.remote_ocr_server.validation import (
    validate_blocks_json,
    validate_pdf_upload,
)
from apps.remote_ocr_server.storage import (
    add_job_file,
    add_node_file,
    create_job,
    delete_job,
    get_node_info,
    get_node_pdf_r2_key,
    save_job_settings,
    update_node_r2_key,
)
from apps.remote_ocr_server.tasks import run_ocr_task

_logger = logging.getLogger(__name__)

# Streaming configuration
_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


async def _stream_upload_pdf(
    upload_file: UploadFile,
    s3_client,
    bucket_name: str,
    r2_key: str,
) -> int:
    """Streaming upload PDF в R2 без загрузки в память.

    Returns:
        int: размер файла в байтах
    """
    # Получаем размер файла
    await upload_file.seek(0, 2)  # SEEK_END
    file_size = await upload_file.tell()
    await upload_file.seek(0)

    if file_size < _CHUNK_SIZE:
        # Маленький файл - простой upload
        content = await upload_file.read()
        s3_client.put_object(
            Bucket=bucket_name,
            Key=r2_key,
            Body=content,
            ContentType="application/pdf",
        )
    else:
        # Большой файл - multipart upload
        response = s3_client.create_multipart_upload(
            Bucket=bucket_name,
            Key=r2_key,
            ContentType="application/pdf",
        )
        upload_id = response["UploadId"]
        parts = []
        part_number = 1

        try:
            while True:
                chunk = await upload_file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                part_response = s3_client.upload_part(
                    Bucket=bucket_name,
                    Key=r2_key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=chunk,
                )
                parts.append({
                    "PartNumber": part_number,
                    "ETag": part_response["ETag"],
                })
                part_number += 1

            s3_client.complete_multipart_upload(
                Bucket=bucket_name,
                Key=r2_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except Exception:
            s3_client.abort_multipart_upload(
                Bucket=bucket_name,
                Key=r2_key,
                UploadId=upload_id,
            )
            raise

    return file_size


async def create_job_handler(
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

    # Validate PDF file (magic bytes, size)
    await validate_pdf_upload(pdf)

    # Validate blocks JSON
    blocks_json = (await blocks_file.read()).decode("utf-8")
    blocks_data = validate_blocks_json(blocks_json)

    _logger.info(
        f"POST /jobs: document_id={document_id[:16]}..., node_id={node_id}"
    )

    job_id = str(uuid.uuid4())

    # Определяем r2_prefix - папку для файлов задачи
    pdf_needs_upload = False

    if node_id:
        from pathlib import PurePosixPath

        pdf_r2_key = get_node_pdf_r2_key(node_id)
        if pdf_r2_key:
            try:
                s3_check, bucket_check = get_r2_sync_client()
                s3_check.head_object(Bucket=bucket_check, Key=pdf_r2_key)
            except Exception:
                _logger.warning(f"PDF not found in R2, will upload: {pdf_r2_key}")
                pdf_needs_upload = True
            # PDF остаётся в родительской папке node
            pdf_parent = str(PurePosixPath(pdf_r2_key).parent)
        else:
            node_info = get_node_info(node_id)
            if node_info and node_info.get("parent_id"):
                pdf_parent = f"tree_docs/{node_info['parent_id']}"
            else:
                pdf_parent = f"tree_docs/{node_id}"
            pdf_r2_key = f"{pdf_parent}/{document_name}"
            pdf_needs_upload = True

        # r2_prefix теперь изолирован для каждой задачи
        r2_prefix = f"tree_docs/{node_id}/ocr_runs/{job_id}"
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

    can_accept, queue_size, max_size = check_queue_capacity()
    if not can_accept:
        raise HTTPException(
            status_code=503,
            detail=f"Queue is full ({queue_size}/{max_size}). Try again later.",
        )

    try:
        s3_client, bucket_name = get_r2_sync_client()

        if node_id:
            if pdf_needs_upload:
                pdf_key = pdf_r2_key or f"{pdf_parent}/{document_name}"
                pdf_size = await _stream_upload_pdf(
                    pdf, s3_client, bucket_name, pdf_key
                )
                _logger.info(f"Uploaded PDF to R2: {pdf_key} ({pdf_size} bytes)")

                add_node_file(
                    node_id,
                    "pdf",
                    pdf_key,
                    document_name,
                    pdf_size,
                    "application/pdf",
                )
                update_node_r2_key(node_id, pdf_key)
            else:
                pdf_key = pdf_r2_key

            # Blocks сохраняются в изолированной папке задачи
            blocks_bytes = json.dumps(blocks_data, ensure_ascii=False, indent=2).encode(
                "utf-8"
            )
            blocks_key = f"{r2_prefix}/annotation.json"
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
                "annotation.json",
                len(blocks_bytes),
            )
            add_job_file(job.id, "pdf", pdf_key, document_name, 0)
        else:
            pdf_key = f"{r2_prefix}/document.pdf"
            pdf_size = await _stream_upload_pdf(pdf, s3_client, bucket_name, pdf_key)
            add_job_file(job.id, "pdf", pdf_key, "document.pdf", pdf_size)

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
