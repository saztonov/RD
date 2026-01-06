"""HTTP-клиент для удалённого OCR сервера"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import httpx

from app.ocr_client.exceptions import (
    AuthenticationError,
    PayloadTooLargeError,
    RemoteOCRError,
    ServerError,
)
from app.ocr_client.http_pool import get_remote_ocr_client
from app.ocr_client.models import JobInfo
from rd_core.models import Block

logger = logging.getLogger(__name__)


@dataclass
class RemoteOCRClient:
    """Клиент для удалённого OCR сервера"""

    base_url: str = field(
        default_factory=lambda: os.getenv(
            "REMOTE_OCR_BASE_URL", "http://localhost:8000"
        )
    )
    api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("REMOTE_OCR_API_KEY")
    )
    timeout: float = 120.0
    upload_timeout: float = 600.0  # Для POST /jobs - большие PDF
    max_retries: int = 3

    def __post_init__(self):
        """Логирование конфигурации при инициализации"""
        logger.info(
            f"RemoteOCRClient initialized: base_url={self.base_url}, "
            f"api_key={'***' if self.api_key else 'None'}"
        )

    def _headers(self) -> dict:
        """Получить заголовки для запросов"""
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _handle_response_error(self, resp: httpx.Response):
        """Обработать ошибки ответа с понятными сообщениями"""
        if resp.status_code == 401:
            raise AuthenticationError("Неверный API ключ (REMOTE_OCR_API_KEY)")
        elif resp.status_code == 413:
            raise PayloadTooLargeError("Файл слишком большой для загрузки")
        elif resp.status_code >= 500:
            raise ServerError(f"Ошибка сервера: {resp.status_code}")
        resp.raise_for_status()

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
        **kwargs,
    ) -> httpx.Response:
        """Выполнить запрос с ретраями и exponential backoff"""
        timeout = timeout or self.timeout
        retries = retries if retries is not None else self.max_retries

        last_error = None
        client = get_remote_ocr_client(self.base_url, timeout)
        for attempt in range(retries):
            try:
                resp = getattr(client, method)(
                    path, headers=self._headers(), timeout=timeout, **kwargs
                )

                # Для 5xx - ретраим
                if resp.status_code >= 500 and attempt < retries - 1:
                    delay = 2**attempt  # 1, 2, 4 сек
                    logger.warning(
                        f"Сервер вернул {resp.status_code}, ретрай через {delay}с..."
                    )
                    time.sleep(delay)
                    continue

                self._handle_response_error(resp)
                return resp

            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as e:
                last_error = e
                if attempt < retries - 1:
                    delay = 2**attempt
                    logger.warning(f"Сетевая ошибка: {e}, ретрай через {delay}с...")
                    time.sleep(delay)
                    continue
                # Не выбрасываем исключение - просто логируем
                logger.error(f"Все попытки подключения исчерпаны: {e}")
                from app.gui.connection_manager import is_network_error

                if is_network_error(e):
                    raise RemoteOCRError(f"Сервер недоступен: {e}")
                raise

        if last_error:
            raise last_error

    @staticmethod
    def hash_pdf(path: str) -> str:
        """Вычислить SHA256 хеш PDF файла"""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def health(self) -> bool:
        """Проверить доступность сервера"""
        url = f"{self.base_url}/health"
        try:
            logger.debug(f"Health check: GET {url}")
            client = get_remote_ocr_client(self.base_url, self.timeout)
            resp = client.get("/health", headers=self._headers(), timeout=2.0)
            logger.debug(f"Health check response: {resp.status_code}")
            return resp.status_code == 200 and resp.json().get("ok", False)
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.TimeoutException,
            httpx.NetworkError,
        ) as e:
            logger.debug(f"Health check network error: {e}")
            return False
        except Exception as e:
            logger.warning(f"Health check failed: {url} -> {e}")
            return False

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

    def get_job_details(self, job_id: str) -> dict:
        """Получить детальную информацию о задаче"""
        resp = self._request_with_retry("get", f"/jobs/{job_id}/details")
        return resp.json()

    def download_result(self, job_id: str, target_zip_path: str) -> str:
        """
        Скачать результат задачи

        Args:
            job_id: ID задачи
            target_zip_path: путь для сохранения zip

        Returns:
            Путь к скачанному файлу
        """
        resp = self._request_with_retry("get", f"/jobs/{job_id}/result", timeout=300.0)

        Path(target_zip_path).parent.mkdir(parents=True, exist_ok=True)
        with open(target_zip_path, "wb") as f:
            f.write(resp.content)

        return target_zip_path

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

    def get_job_blocks(self, job_id: str) -> Optional[List[dict]]:
        """
        Получить блоки задачи с сервера

        Args:
            job_id: ID задачи

        Returns:
            Список блоков или None
        """
        try:
            details = self.get_job_details(job_id)
            r2_base_url = details.get("r2_base_url")

            if not r2_base_url:
                return None

            # Получаем блоки из R2
            blocks_url = f"{r2_base_url}/annotation.json"
            resp = httpx.get(blocks_url, timeout=30.0)
            if resp.status_code == 200:
                return resp.json()

            # Fallback на blocks.json
            blocks_url = f"{r2_base_url}/blocks.json"
            resp = httpx.get(blocks_url, timeout=30.0)
            if resp.status_code == 200:
                return resp.json()

        except Exception as e:
            logger.warning(f"Ошибка получения блоков: {e}")

        return None

    def pause_job(self, job_id: str) -> bool:
        """Поставить задачу на паузу"""
        resp = self._request_with_retry("post", f"/jobs/{job_id}/pause")
        return resp.json().get("ok", False)

    def resume_job(self, job_id: str) -> bool:
        """Возобновить задачу с паузы"""
        resp = self._request_with_retry("post", f"/jobs/{job_id}/resume")
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


# Для обратной совместимости
RemoteOcrClient = RemoteOCRClient
