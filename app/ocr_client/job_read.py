"""Миксин чтения OCR задач."""
from __future__ import annotations

import logging
import time
from typing import List, Optional

import httpx

from app.ocr_client.exceptions import JobNotFoundError
from rd_core.dto.jobs import JobInfoDTO

# Re-export as JobInfo for backward compatibility
JobInfo = JobInfoDTO

logger = logging.getLogger(__name__)


def _parse_job(j: dict) -> JobInfo:
    """Парсинг JSON задачи в JobInfo через shared DTO."""
    return JobInfo.from_dict(j)


class JobReadMixin:
    """Чтение и поиск OCR задач."""

    def find_existing_job(self, document_id: str) -> Optional[JobInfo]:
        """Найти существующую активную задачу для документа."""
        try:
            jobs, _ = self.list_jobs(document_id=document_id)
            for job in jobs:
                if job.status in ("queued", "processing"):
                    logger.info(
                        f"Найдена существующая задача {job.id} в статусе {job.status}"
                    )
                    return job
        except Exception as e:
            logger.warning(f"Ошибка поиска существующей задачи: {e}")
        return None

    def list_jobs(
        self, document_id: Optional[str] = None, since: Optional[str] = None
    ) -> tuple[List[JobInfo], str]:
        """Получить список задач. При since — только изменённые."""
        params = {}
        if document_id:
            params["document_id"] = document_id
        if since:
            params["since"] = since

        logger.info(f"list_jobs: GET {self.base_url}/jobs params={params}")
        t0 = time.time()
        resp = self._request_with_retry("get", "/jobs", params=params)
        elapsed = time.time() - t0
        logger.info(
            f"list_jobs response: status={resp.status_code}, "
            f"size={len(resp.content)}B, elapsed={elapsed:.2f}s"
        )
        data = resp.json()

        jobs = [_parse_job(j) for j in data.get("jobs", [])]
        return jobs, data.get("server_time", "")

    def get_job(self, job_id: str) -> JobInfo:
        """Получить информацию о задаче. Raises JobNotFoundError при 404."""
        try:
            resp = self._request_with_retry("get", f"/jobs/{job_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise JobNotFoundError(job_id) from e
            raise
        return _parse_job(resp.json())

    def get_job_details(self, job_id: str) -> dict:
        """Получить детальную информацию о задаче. Raises JobNotFoundError при 404."""
        try:
            resp = self._request_with_retry("get", f"/jobs/{job_id}/details")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise JobNotFoundError(job_id) from e
            raise
        return resp.json()
