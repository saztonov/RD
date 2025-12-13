"""HTTP-клиент для удалённого OCR сервера"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import httpx

from rd_core.models import Block


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
    updated_at: str = ""
    error_message: Optional[str] = None


@dataclass
class RemoteOCRClient:
    """Клиент для удалённого OCR сервера"""
    base_url: str = field(default_factory=lambda: os.getenv("REMOTE_OCR_BASE_URL", "http://localhost:8000"))
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("REMOTE_OCR_API_KEY"))
    client_id: str = field(default_factory=_get_or_create_client_id)
    timeout: float = 120.0
    
    def _headers(self) -> dict:
        """Получить заголовки для запросов"""
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers
    
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
            with httpx.Client(base_url=self.base_url, timeout=2.0) as client:
                resp = client.get("/health", headers=self._headers())
                return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception:
            return False
    
    def create_job(
        self,
        pdf_path: str,
        selected_blocks: List[Block],
        engine: str = "openrouter"
    ) -> JobInfo:
        """
        Создать задачу OCR
        
        Args:
            pdf_path: путь к PDF файлу
            selected_blocks: список выбранных блоков
            engine: движок OCR
        
        Returns:
            JobInfo с информацией о созданной задаче
        """
        document_id = self.hash_pdf(pdf_path)
        document_name = Path(pdf_path).name
        
        # Сериализуем блоки
        blocks_data = [block.to_dict() for block in selected_blocks]
        blocks_json = json.dumps(blocks_data, ensure_ascii=False)
        
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            with open(pdf_path, "rb") as pdf_file:
                resp = client.post(
                    "/jobs",
                    headers=self._headers(),
                    data={
                        "client_id": self.client_id,
                        "document_id": document_id,
                        "document_name": document_name,
                        "engine": engine,
                        "blocks_json": blocks_json,
                    },
                    files={"pdf": (document_name, pdf_file, "application/pdf")}
                )
            resp.raise_for_status()
            data = resp.json()
        
        return JobInfo(
            id=data["id"],
            status=data["status"],
            progress=data["progress"],
            document_id=data["document_id"],
            document_name=data["document_name"]
        )
    
    def list_jobs(self, document_id: Optional[str] = None) -> List[JobInfo]:
        """
        Получить список задач
        
        Args:
            document_id: опционально фильтр по document_id
        
        Returns:
            Список задач
        """
        params = {"client_id": self.client_id}
        if document_id:
            params["document_id"] = document_id
        
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            resp = client.get("/jobs", params=params, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        
        return [
            JobInfo(
                id=j["id"],
                status=j["status"],
                progress=j["progress"],
                document_id=j["document_id"],
                document_name=j["document_name"],
                updated_at=j.get("updated_at", ""),
                error_message=j.get("error_message")
            )
            for j in data
        ]
    
    def get_job(self, job_id: str) -> JobInfo:
        """Получить информацию о задаче"""
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            resp = client.get(f"/jobs/{job_id}", headers=self._headers())
            resp.raise_for_status()
            j = resp.json()
        
        return JobInfo(
            id=j["id"],
            status=j["status"],
            progress=j["progress"],
            document_id=j["document_id"],
            document_name=j["document_name"],
            updated_at=j.get("updated_at", ""),
            error_message=j.get("error_message")
        )
    
    def get_job_details(self, job_id: str) -> dict:
        """Получить детальную информацию о задаче"""
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            resp = client.get(f"/jobs/{job_id}/details", headers=self._headers())
            resp.raise_for_status()
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
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            resp = client.get(f"/jobs/{job_id}/result", headers=self._headers())
            resp.raise_for_status()
            
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
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            resp = client.delete(f"/jobs/{job_id}", headers=self._headers())
            resp.raise_for_status()
            return resp.json().get("ok", False)


# Для обратной совместимости
RemoteOcrClient = RemoteOCRClient
