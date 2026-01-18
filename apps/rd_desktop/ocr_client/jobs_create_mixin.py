"""Mixin для создания OCR задач"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

import httpx

from apps.rd_desktop.client_id import get_client_id
from apps.rd_desktop.ocr_client.exceptions import RemoteOCRError
from apps.rd_desktop.ocr_client.http_pool import get_remote_ocr_client
from apps.rd_desktop.ocr_client.models import JobInfo
from rd_domain.models import Block

logger = logging.getLogger(__name__)


class JobsCreateMixin:
    """Методы создания OCR задач"""

    def find_existing_job(self, document_id: str) -> Optional[JobInfo]:
        """
        Найти существующую активную задачу для документа

        Returns:
            JobInfo если есть queued/processing задача, иначе None
        """
        try:
            jobs = self.list_jobs(document_id=document_id)
            for job in jobs:
                if job.status in ("queued", "processing"):
                    logger.info(
                        f"Найдена существующая задача {job.id} в статусе {job.status}"
                    )
                    return job
        except Exception as e:
            logger.warning(f"Ошибка поиска существующей задачи: {e}")
        return None

    def create_job(
        self,
        pdf_path: str,
        selected_blocks: List[Block],
        task_name: str = "",
        engine: str = "openrouter",
        text_model: Optional[str] = None,
        table_model: Optional[str] = None,
        image_model: Optional[str] = None,
        stamp_model: Optional[str] = None,
        reuse_existing: bool = True,
        node_id: Optional[str] = None,
    ) -> JobInfo:
        """
        Создать задачу OCR

        Args:
            pdf_path: путь к PDF файлу
            selected_blocks: список выбранных блоков
            task_name: название задания
            engine: движок OCR
            text_model: модель для текста
            table_model: модель для таблиц
            image_model: модель для изображений
            stamp_model: модель для штампов
            reuse_existing: переиспользовать существующую задачу если есть
            node_id: ID узла дерева для связи результатов

        Returns:
            JobInfo с информацией о созданной/существующей задаче
        """
        document_id = self.hash_pdf(pdf_path)
        document_name = Path(pdf_path).name

        # Проверяем существующую активную задачу
        if reuse_existing:
            existing = self.find_existing_job(document_id)
            if existing:
                logger.info(f"Подключаемся к существующей задаче {existing.id}")
                return existing

        # Сериализуем блоки
        blocks_data = [block.to_dict() for block in selected_blocks]
        blocks_json = json.dumps(blocks_data, ensure_ascii=False)
        blocks_bytes = blocks_json.encode("utf-8")

        # Используем увеличенный таймаут для загрузки
        client = get_remote_ocr_client(self.base_url, self.upload_timeout)
        with open(pdf_path, "rb") as pdf_file:
            form_data = {
                "client_id": get_client_id(),
                "document_id": document_id,
                "document_name": document_name,
                "task_name": task_name,
                "engine": engine,
            }
            if text_model:
                form_data["text_model"] = text_model
            if table_model:
                form_data["table_model"] = table_model
            if image_model:
                form_data["image_model"] = image_model
            if stamp_model:
                form_data["stamp_model"] = stamp_model
            if node_id:
                form_data["node_id"] = node_id

            resp = client.post(
                "/jobs",
                headers=self._headers(),
                data=form_data,
                timeout=self.upload_timeout,
                files={
                    "pdf": (document_name, pdf_file, "application/pdf"),
                    "blocks_file": ("blocks.json", blocks_bytes, "application/json"),
                },
            )
        logger.info(f"POST /jobs response: {resp.status_code}")
        if resp.status_code >= 400:
            logger.error(f"POST /jobs error response: {resp.text[:1000]}")
        self._handle_response_error(resp)
        data = resp.json()

        return JobInfo(
            id=data["id"],
            status=data["status"],
            progress=data["progress"],
            document_id=data["document_id"],
            document_name=data["document_name"],
            task_name=data.get("task_name", ""),
        )

    def create_job_v2(
        self,
        pdf_path: str,
        selected_blocks: List[Block],
        task_name: str = "",
        engine: str = "openrouter",
        text_model: Optional[str] = None,
        table_model: Optional[str] = None,
        image_model: Optional[str] = None,
        stamp_model: Optional[str] = None,
        reuse_existing: bool = True,
        node_id: Optional[str] = None,
    ) -> JobInfo:
        """
        Create OCR job using direct R2 upload (v2 API).

        This method bypasses the server for file uploads:
        1. POST /jobs/init - get presigned URLs
        2. PUT files directly to R2 using presigned URLs
        3. POST /jobs/{id}/confirm - confirm and queue job

        Benefits:
        - Faster uploads (direct to R2)
        - Reduced server load
        - Better handling of large PDFs

        Falls back to v1 API (create_job) on errors.
        """
        document_id = self.hash_pdf(pdf_path)
        document_name = Path(pdf_path).name

        # Check for existing job
        if reuse_existing:
            existing = self.find_existing_job(document_id)
            if existing:
                logger.info(f"Подключаемся к существующей задаче {existing.id}")
                return existing

        # Serialize blocks
        blocks_data = [block.to_dict() for block in selected_blocks]
        blocks_json = json.dumps(blocks_data, ensure_ascii=False)
        blocks_bytes = blocks_json.encode("utf-8")

        # Get file sizes
        pdf_size = Path(pdf_path).stat().st_size

        try:
            # Step 1: Initialize job and get presigned URLs
            client = get_remote_ocr_client(self.base_url, self.timeout)

            form_data = {
                "client_id": get_client_id(),
                "document_id": document_id,
                "document_name": document_name,
                "task_name": task_name,
                "engine": engine,
                "pdf_size": str(pdf_size),
                "blocks_size": str(len(blocks_bytes)),
            }
            if text_model:
                form_data["text_model"] = text_model
            if table_model:
                form_data["table_model"] = table_model
            if image_model:
                form_data["image_model"] = image_model
            if stamp_model:
                form_data["stamp_model"] = stamp_model
            if node_id:
                form_data["node_id"] = node_id

            resp = client.post(
                "/jobs/init",
                headers=self._headers(),
                data=form_data,
                timeout=self.timeout,
            )

            if resp.status_code >= 400:
                logger.warning(f"Init failed ({resp.status_code}), falling back to v1")
                return self.create_job(
                    pdf_path, selected_blocks, task_name, engine,
                    text_model, table_model, image_model, stamp_model,
                    reuse_existing=False, node_id=node_id,
                )

            init_data = resp.json()
            job_id = init_data["job_id"]
            presigned_urls = init_data["presigned_urls"]

            logger.info(f"Job {job_id} initialized, uploading files directly to R2...")

            # Step 2: Upload files directly to R2
            # Upload PDF (if presigned URL provided)
            if presigned_urls.get("pdf"):
                with open(pdf_path, "rb") as pdf_file:
                    pdf_resp = httpx.put(
                        presigned_urls["pdf"],
                        content=pdf_file,
                        headers={"Content-Type": "application/pdf"},
                        timeout=self.upload_timeout,
                    )
                    if pdf_resp.status_code not in (200, 201):
                        logger.error(f"PDF upload failed: {pdf_resp.status_code}")
                        raise RemoteOCRError(f"PDF upload failed: {pdf_resp.status_code}")

                logger.info(f"PDF uploaded directly to R2 ({pdf_size / 1024 / 1024:.1f} MB)")

            # Upload blocks
            blocks_resp = httpx.put(
                presigned_urls["blocks"],
                content=blocks_bytes,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            if blocks_resp.status_code not in (200, 201):
                logger.error(f"Blocks upload failed: {blocks_resp.status_code}")
                raise RemoteOCRError(f"Blocks upload failed: {blocks_resp.status_code}")

            logger.info(f"Blocks uploaded directly to R2 ({len(blocks_bytes)} bytes)")

            # Step 3: Confirm upload and queue job
            confirm_resp = client.post(
                f"/jobs/{job_id}/confirm",
                headers=self._headers(),
                timeout=self.timeout,
            )

            if confirm_resp.status_code >= 400:
                logger.error(f"Confirm failed: {confirm_resp.status_code}")
                raise RemoteOCRError(f"Confirm failed: {confirm_resp.text}")

            data = confirm_resp.json()
            logger.info(f"Job {job_id} confirmed and queued (v2 API)")

            return JobInfo(
                id=data["id"],
                status=data["status"],
                progress=data["progress"],
                document_id=data["document_id"],
                document_name=data["document_name"],
                task_name=data.get("task_name", ""),
            )

        except RemoteOCRError:
            raise
        except Exception as e:
            logger.warning(f"V2 API failed ({e}), falling back to v1")
            return self.create_job(
                pdf_path, selected_blocks, task_name, engine,
                text_model, table_model, image_model, stamp_model,
                reuse_existing=False, node_id=node_id,
            )
