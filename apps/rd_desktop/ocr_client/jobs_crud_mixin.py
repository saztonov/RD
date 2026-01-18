"""Mixin для CRUD операций с OCR задачами"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from apps.rd_desktop.ocr_client.http_pool import get_remote_ocr_client
from apps.rd_desktop.ocr_client.models import JobInfo
from rd_domain.models import Block

logger = logging.getLogger(__name__)


class JobsCrudMixin:
    """CRUD операции с задачами"""

    def list_jobs(
        self, document_id: Optional[str] = None
    ) -> List[JobInfo]:
        """
        Получить список задач

        Args:
            document_id: опционально фильтр по document_id

        Returns:
            Список задач
        """
        params = {}
        if document_id:
            params["document_id"] = document_id

        logger.debug(f"list_jobs: GET {self.base_url}/jobs params={params}")
        resp = self._request_with_retry("get", "/jobs", params=params)
        logger.debug(f"list_jobs response: {resp.status_code}, len={len(resp.content)}")
        data = resp.json()

        return [
            JobInfo(
                id=j["id"],
                status=j["status"],
                progress=j["progress"],
                document_id=j["document_id"],
                document_name=j["document_name"],
                task_name=j.get("task_name", ""),
                created_at=j.get("created_at", ""),
                updated_at=j.get("updated_at", ""),
                error_message=j.get("error_message"),
                node_id=j.get("node_id"),
                status_message=j.get("status_message"),
            )
            for j in data
        ]

    def get_jobs_changes(self, since: str) -> tuple[List[JobInfo], str]:
        """
        Получить задачи, изменённые после указанного времени.

        Используется для incremental polling - запрашиваем только изменения
        вместо полного списка.

        Args:
            since: ISO timestamp для фильтрации

        Returns:
            Кортеж (список изменённых задач, server_time для следующего запроса)
        """
        params = {"since": since}
        logger.debug(
            f"get_jobs_changes: GET {self.base_url}/jobs/changes params={params}"
        )
        resp = self._request_with_retry("get", "/jobs/changes", params=params)
        data = resp.json()

        jobs = [
            JobInfo(
                id=j["id"],
                status=j["status"],
                progress=j["progress"],
                document_id=j["document_id"],
                document_name=j["document_name"],
                task_name=j.get("task_name", ""),
                created_at=j.get("created_at", ""),
                updated_at=j.get("updated_at", ""),
                error_message=j.get("error_message"),
                node_id=j.get("node_id"),
                status_message=j.get("status_message"),
            )
            for j in data.get("jobs", [])
        ]

        return jobs, data.get("server_time", "")

    def get_job(self, job_id: str) -> JobInfo:
        """Получить информацию о задаче"""
        resp = self._request_with_retry("get", f"/jobs/{job_id}")
        j = resp.json()

        return JobInfo(
            id=j["id"],
            status=j["status"],
            progress=j["progress"],
            document_id=j["document_id"],
            document_name=j["document_name"],
            task_name=j.get("task_name", ""),
            created_at=j.get("created_at", ""),
            updated_at=j.get("updated_at", ""),
            error_message=j.get("error_message"),
            node_id=j.get("node_id"),
            status_message=j.get("status_message"),
        )

    def delete_job(self, job_id: str) -> bool:
        """
        Удалить задачу и все связанные файлы

        Args:
            job_id: ID задачи

        Returns:
            True если успешно удалено
        """
        resp = self._request_with_retry("delete", f"/jobs/{job_id}")
        return resp.json().get("ok", False)

    def restart_job(
        self, job_id: str, updated_blocks: Optional[List[Block]] = None
    ) -> bool:
        """
        Перезапустить задачу (сбросить результаты и поставить в очередь)

        Args:
            job_id: ID задачи
            updated_blocks: опционально обновлённые блоки

        Returns:
            True если успешно
        """
        if updated_blocks:
            blocks_data = [block.to_dict() for block in updated_blocks]
            blocks_json = json.dumps(blocks_data, ensure_ascii=False)
            blocks_bytes = blocks_json.encode("utf-8")

            client = get_remote_ocr_client(self.base_url, self.timeout)
            resp = client.post(
                f"/jobs/{job_id}/restart",
                headers=self._headers(),
                timeout=self.timeout,
                files={
                    "blocks_file": ("blocks.json", blocks_bytes, "application/json")
                },
            )
            self._handle_response_error(resp)
            return resp.json().get("ok", False)

        resp = self._request_with_retry("post", f"/jobs/{job_id}/restart")
        return resp.json().get("ok", False)

    def cancel_job(self, job_id: str) -> bool:
        """Отменить задачу"""
        resp = self._request_with_retry("post", f"/jobs/{job_id}/cancel")
        return resp.json().get("ok", False)

    def rename_job(self, job_id: str, task_name: str) -> bool:
        """
        Переименовать задачу

        Args:
            job_id: ID задачи
            task_name: новое название

        Returns:
            True если успешно
        """
        resp = self._request_with_retry(
            "patch", f"/jobs/{job_id}", data={"task_name": task_name}
        )
        return resp.json().get("ok", False)

    def start_job(
        self,
        job_id: str,
        engine: str = "openrouter",
        text_model: Optional[str] = None,
        table_model: Optional[str] = None,
        image_model: Optional[str] = None,
        stamp_model: Optional[str] = None,
    ) -> bool:
        """
        Запустить черновик на распознавание

        Args:
            job_id: ID задачи (черновика)
            engine: движок OCR
            text_model: модель для текста
            table_model: модель для таблиц
            image_model: модель для изображений
            stamp_model: модель для штампов

        Returns:
            True если успешно
        """
        data = {
            "engine": engine,
            "text_model": text_model or "",
            "table_model": table_model or "",
            "image_model": image_model or "",
            "stamp_model": stamp_model or "",
        }
        resp = self._request_with_retry("post", f"/jobs/{job_id}/start", data=data)
        return resp.json().get("ok", False)
