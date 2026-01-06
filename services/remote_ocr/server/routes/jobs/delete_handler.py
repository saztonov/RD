"""Обработчик удаления задачи OCR"""
import logging
from typing import Optional

from fastapi import Header, HTTPException

from services.remote_ocr.server.routes.common import (
    check_api_key,
    get_r2_sync_client,
)
from services.remote_ocr.server.storage import (
    delete_job,
    get_job,
)

_logger = logging.getLogger(__name__)


def delete_job_handler(
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
