"""HTTP-клиент для удалённого OCR сервера"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from httpx import Limits

from rd_core.models import Block

logger = logging.getLogger(__name__)

# Глобальный пул соединений для Remote OCR
_remote_ocr_http_client: httpx.Client | None = None
_remote_ocr_base_url: str | None = None

def _get_remote_ocr_client(base_url: str, timeout: float = 120.0) -> httpx.Client:
    """Получить или создать HTTP клиент с connection pooling"""
    global _remote_ocr_http_client, _remote_ocr_base_url
    if _remote_ocr_http_client is None or _remote_ocr_base_url != base_url:
        if _remote_ocr_http_client is not None:
            try:
                _remote_ocr_http_client.close()
            except Exception:
                pass
        _remote_ocr_http_client = httpx.Client(
            base_url=base_url,
            limits=Limits(max_connections=10, max_keepalive_connections=5),
            timeout=timeout,
        )
        _remote_ocr_base_url = base_url
    return _remote_ocr_http_client


class RemoteOCRError(Exception):
    """Базовая ошибка Remote OCR"""
    pass


class AuthenticationError(RemoteOCRError):
    """Неверный API ключ (401)"""
    pass


class PayloadTooLargeError(RemoteOCRError):
    """Слишком большой файл (413)"""
    pass


class ServerError(RemoteOCRError):
    """Ошибка сервера (5xx)"""
    pass


def _get_client_id_path() -> Path:
    """Получить путь к файлу client_id"""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    return base / "RD" / "client_id.txt"


def _get_or_create_client_id() -> str:
    """Получить или создать client_id"""
    # Сначала проверяем env
    env_id = os.getenv("REMOTE_OCR_CLIENT_ID")
    if env_id:
        return env_id
    
    # Иначе читаем/создаём файл
    id_path = _get_client_id_path()
    
    if id_path.exists():
        try:
            return id_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    
    # Генерируем новый
    new_id = str(uuid.uuid4())
    try:
        id_path.parent.mkdir(parents=True, exist_ok=True)
        id_path.write_text(new_id, encoding="utf-8")
    except Exception:
        pass  # Если не получилось сохранить, используем временный
    
    return new_id


@dataclass
class JobInfo:
    """Информация о задаче"""
    id: str
    status: str
    progress: float
    document_id: str
    document_name: str
    task_name: str = ""
    created_at: str = ""
    updated_at: str = ""
    error_message: Optional[str] = None


@dataclass
class RemoteOCRClient:
    """Клиент для удалённого OCR сервера"""
    base_url: str = field(default_factory=lambda: os.getenv("REMOTE_OCR_BASE_URL", "http://localhost:8000"))
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("REMOTE_OCR_API_KEY"))
    client_id: str = field(default_factory=_get_or_create_client_id)
    timeout: float = 120.0
    upload_timeout: float = 600.0  # Для POST /jobs - большие PDF
    max_retries: int = 3
    
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
        **kwargs
    ) -> httpx.Response:
        """Выполнить запрос с ретраями и exponential backoff"""
        timeout = timeout or self.timeout
        retries = retries if retries is not None else self.max_retries
        
        last_error = None
        client = _get_remote_ocr_client(self.base_url, timeout)
        for attempt in range(retries):
            try:
                resp = getattr(client, method)(path, headers=self._headers(), timeout=timeout, **kwargs)
                
                # Для 5xx - ретраим
                if resp.status_code >= 500 and attempt < retries - 1:
                    delay = 2 ** attempt  # 1, 2, 4 сек
                    logger.warning(f"Сервер вернул {resp.status_code}, ретрай через {delay}с...")
                    time.sleep(delay)
                    continue
                
                self._handle_response_error(resp)
                return resp
                    
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < retries - 1:
                    delay = 2 ** attempt
                    logger.warning(f"Сетевая ошибка: {e}, ретрай через {delay}с...")
                    time.sleep(delay)
                    continue
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
        try:
            client = _get_remote_ocr_client(self.base_url, self.timeout)
            resp = client.get("/health", headers=self._headers(), timeout=2.0)
            return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception:
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
                    logger.info(f"Найдена существующая задача {job.id} в статусе {job.status}")
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
        client = _get_remote_ocr_client(self.base_url, self.upload_timeout)
        with open(pdf_path, "rb") as pdf_file:
            form_data = {
                "client_id": self.client_id,
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
                }
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
            task_name=data.get("task_name", "")
        )
    
    def list_jobs(self, document_id: Optional[str] = None, all_clients: bool = True) -> List[JobInfo]:
        """
        Получить список задач
        
        Args:
            document_id: опционально фильтр по document_id
            all_clients: если True - возвращает задачи всех пользователей
        
        Returns:
            Список задач
        """
        params = {}
        if not all_clients:
            params["client_id"] = self.client_id
        if document_id:
            params["document_id"] = document_id
        
        resp = self._request_with_retry("get", "/jobs", params=params)
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
                error_message=j.get("error_message")
            )
            for j in data
        ]
    
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
            error_message=j.get("error_message")
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
    
    def restart_job(self, job_id: str) -> bool:
        """
        Перезапустить задачу (сбросить результаты и поставить в очередь)
        
        Args:
            job_id: ID задачи
        
        Returns:
            True если успешно
        """
        resp = self._request_with_retry("post", f"/jobs/{job_id}/restart")
        return resp.json().get("ok", False)
    
    def pause_job(self, job_id: str) -> bool:
        """Поставить задачу на паузу"""
        resp = self._request_with_retry("post", f"/jobs/{job_id}/pause")
        return resp.json().get("ok", False)
    
    def resume_job(self, job_id: str) -> bool:
        """Возобновить задачу с паузы"""
        resp = self._request_with_retry("post", f"/jobs/{job_id}/resume")
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
        resp = self._request_with_retry("patch", f"/jobs/{job_id}", data={"task_name": task_name})
        return resp.json().get("ok", False)
    
    def start_job(
        self,
        job_id: str,
        engine: str = "openrouter",
        text_model: Optional[str] = None,
        table_model: Optional[str] = None,
        image_model: Optional[str] = None,
    ) -> bool:
        """
        Запустить черновик на распознавание
        
        Args:
            job_id: ID задачи (черновика)
            engine: движок OCR
            text_model: модель для текста
            table_model: модель для таблиц
            image_model: модель для изображений
        
        Returns:
            True если успешно
        """
        data = {
            "engine": engine,
            "text_model": text_model or "",
            "table_model": table_model or "",
            "image_model": image_model or "",
        }
        resp = self._request_with_retry("post", f"/jobs/{job_id}/start", data=data)
        return resp.json().get("ok", False)


# Для обратной совместимости
RemoteOcrClient = RemoteOCRClient
