"""
Унифицированный клиент для работы через Remote OCR Server API
Заменяет прямой доступ к TreeClient и R2Storage
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from httpx import Limits

from app.tree_models import TreeNode, NodeType, NodeStatus, FileType, NodeFile, StageType, SectionType

logger = logging.getLogger(__name__)

# Глобальный HTTP клиент
_unified_http_client: httpx.Client | None = None


def _get_unified_client(base_url: str, timeout: float = 30.0) -> httpx.Client:
    """Получить или создать HTTP клиент с connection pooling"""
    global _unified_http_client
    if _unified_http_client is None:
        _unified_http_client = httpx.Client(
            base_url=base_url,
            limits=Limits(max_connections=10, max_keepalive_connections=5),
            timeout=timeout,
        )
    return _unified_http_client


@dataclass
class UnifiedClient:
    """
    Унифицированный клиент для работы с Tree и Storage через API
    
    Использование:
        client = UnifiedClient()
        node = client.get_node(node_id)
        client.upload_file(local_path, r2_key)
    """
    base_url: str = field(default_factory=lambda: os.getenv("REMOTE_OCR_BASE_URL", "http://localhost:8000"))
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("REMOTE_OCR_API_KEY"))
    timeout: float = 30.0
    upload_timeout: float = 600.0
    
    def _headers(self) -> dict:
        """Получить заголовки для запросов"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers
    
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Выполнить HTTP запрос"""
        client = _get_unified_client(self.base_url, self.timeout)
        resp = getattr(client, method)(path, headers=self._headers(), **kwargs)
        resp.raise_for_status()
        return resp
    
    # ===== Tree API =====
    
    def is_available(self) -> bool:
        """Проверить доступность API"""
        try:
            resp = self._request("get", "/health")
            return resp.status_code == 200
        except Exception:
            return False
    
    def get_root_nodes(self) -> List[TreeNode]:
        """Получить корневые проекты"""
        resp = self._request("get", "/api/tree/nodes/root")
        return [TreeNode.from_dict(d) for d in resp.json()]
    
    def get_node(self, node_id: str) -> Optional[TreeNode]:
        """Получить узел по ID"""
        try:
            resp = self._request("get", f"/api/tree/nodes/{node_id}")
            return TreeNode.from_dict(resp.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    def get_children(self, parent_id: str) -> List[TreeNode]:
        """Получить дочерние узлы"""
        resp = self._request("get", f"/api/tree/nodes/{parent_id}/children")
        return [TreeNode.from_dict(d) for d in resp.json()]
    
    def create_node(
        self,
        node_type,
        name: str,
        parent_id: Optional[str] = None,
        code: Optional[str] = None,
        attributes: Optional[Dict] = None,
    ) -> TreeNode:
        """Создать новый узел"""
        node_type_str = node_type.value if isinstance(node_type, NodeType) else str(node_type)
        
        payload = {
            "node_type": node_type_str,
            "name": name,
            "parent_id": parent_id,
            "code": code,
            "attributes": attributes or {},
        }
        resp = self._request("post", "/api/tree/nodes", json=payload)
        return TreeNode.from_dict(resp.json())
    
    def update_node(self, node_id: str, **fields) -> Optional[TreeNode]:
        """Обновить узел"""
        update_data = {}
        if "name" in fields:
            update_data["name"] = fields["name"]
        if "code" in fields:
            update_data["code"] = fields["code"]
        if "status" in fields:
            status = fields["status"]
            update_data["status"] = status.value if isinstance(status, NodeStatus) else status
        if "attributes" in fields:
            update_data["attributes"] = fields["attributes"]
        if "sort_order" in fields:
            update_data["sort_order"] = fields["sort_order"]
        if "version" in fields:
            update_data["version"] = fields["version"]
        
        if not update_data:
            return self.get_node(node_id)
        
        try:
            resp = self._request("patch", f"/api/tree/nodes/{node_id}", json=update_data)
            return TreeNode.from_dict(resp.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    def delete_node(self, node_id: str) -> bool:
        """Удалить узел"""
        try:
            self._request("delete", f"/api/tree/nodes/{node_id}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            raise
    
    def update_pdf_status(self, node_id: str, status: str, message: str = None):
        """Обновить статус PDF документа"""
        payload = {"status": status, "message": message}
        self._request("post", f"/api/tree/nodes/{node_id}/pdf-status", json=payload)
    
    def get_pdf_status(self, node_id: str, use_cache: bool = True) -> tuple[str, str]:
        """Получить статус PDF документа"""
        node = self.get_node(node_id)
        if node and hasattr(node, 'pdf_status'):
            return node.pdf_status or "unknown", node.pdf_status_message or ""
        return "unknown", ""
    
    def get_pdf_statuses_batch(self, node_ids: list[str]) -> dict[str, tuple[str, str]]:
        """Получить статусы для нескольких документов"""
        result = {}
        # TODO: Можно оптимизировать батчевым запросом на сервере
        for node_id in node_ids:
            result[node_id] = self.get_pdf_status(node_id, use_cache=False)
        return result
    
    def get_node_files(self, node_id: str, file_type: Optional[FileType] = None) -> List[NodeFile]:
        """Получить файлы узла"""
        params = {}
        if file_type:
            ft = file_type.value if isinstance(file_type, FileType) else file_type
            params["file_type"] = ft
        
        resp = self._request("get", f"/api/tree/nodes/{node_id}/files", params=params)
        return [NodeFile.from_dict(d) for d in resp.json()]
    
    def add_node_file(
        self,
        node_id: str,
        file_type: FileType,
        r2_key: str,
        file_name: str,
        file_size: int = 0,
        mime_type: str = "application/octet-stream",
        metadata: Optional[Dict] = None,
    ) -> NodeFile:
        """Добавить файл к узлу"""
        payload = {
            "file_type": file_type.value if isinstance(file_type, FileType) else file_type,
            "r2_key": r2_key,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "metadata": metadata or {},
        }
        resp = self._request("post", f"/api/tree/nodes/{node_id}/files", json=payload)
        return NodeFile.from_dict(resp.json())
    
    def delete_node_file(self, file_id: str) -> bool:
        """Удалить файл узла"""
        try:
            self._request("delete", f"/api/tree/files/{file_id}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            raise
    
    def add_document(
        self,
        parent_id: str,
        name: str,
        r2_key: str,
        file_size: int = 0,
        mime_type: str = "application/pdf",
        version: int = 1,
    ) -> TreeNode:
        """Добавить документ в папку заданий"""
        attrs = {
            "original_name": name,
            "r2_key": r2_key,
            "file_size": file_size,
            "mime_type": mime_type,
        }
        node = self.create_node(
            node_type=NodeType.DOCUMENT,
            name=name,
            parent_id=parent_id,
            attributes=attrs
        )
        
        # Устанавливаем версию
        self.update_node(node.id, version=version)
        node.version = version
        
        # Регистрируем PDF в node_files
        try:
            self.add_node_file(
                node_id=node.id,
                file_type=FileType.PDF,
                r2_key=r2_key,
                file_name=name,
                file_size=file_size,
                mime_type=mime_type,
            )
        except Exception as e:
            logger.warning(f"Failed to register PDF in node_files: {e}")
        
        return node
    
    def get_stage_types(self) -> List[StageType]:
        """Получить типы стадий"""
        resp = self._request("get", "/api/tree/stage-types")
        return [StageType(**r) for r in resp.json()]
    
    def get_section_types(self) -> List[SectionType]:
        """Получить типы разделов"""
        resp = self._request("get", "/api/tree/section-types")
        return [SectionType(**r) for r in resp.json()]
    
    def get_image_categories(self) -> List[Dict[str, Any]]:
        """Получить категории изображений"""
        resp = self._request("get", "/api/tree/image-categories")
        return resp.json()
    
    def get_image_category_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Получить категорию по коду"""
        try:
            resp = self._request("get", f"/api/tree/image-categories/code/{code}")
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    # ===== Storage API =====
    
    def exists(self, r2_key: str) -> bool:
        """Проверить существование объекта в R2"""
        resp = self._request("get", f"/api/storage/exists/{r2_key}")
        return resp.json()["exists"]
    
    def download_file(self, r2_key: str, local_path: str) -> bool:
        """Скачать файл из R2"""
        try:
            # API возвращает редирект на presigned URL
            client = _get_unified_client(self.base_url, self.timeout)
            
            with client.stream("GET", f"/api/storage/download/{r2_key}", headers=self._headers(), follow_redirects=True) as response:
                response.raise_for_status()
                
                local_file = Path(local_path)
                local_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(local_file, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
            
            logger.debug(f"Downloaded: {r2_key} -> {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"Download failed {r2_key}: {e}")
            return False
    
    def download_text(self, r2_key: str) -> Optional[str]:
        """Скачать текстовый файл из R2"""
        try:
            resp = self._request("get", f"/api/storage/download-text/{r2_key}")
            return resp.json()["content"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    def upload_file(self, local_path: str, r2_key: str, content_type: Optional[str] = None) -> bool:
        """Загрузить файл в R2"""
        try:
            local_file = Path(local_path)
            if not local_file.exists():
                logger.error(f"File not found: {local_path}")
                return False
            
            client = _get_unified_client(self.base_url, self.upload_timeout)
            
            with open(local_file, "rb") as f:
                files = {"file": (local_file.name, f, content_type or "application/octet-stream")}
                resp = client.post(
                    f"/api/storage/upload/{r2_key}",
                    headers={"X-API-Key": self.api_key} if self.api_key else {},
                    files=files,
                    timeout=self.upload_timeout
                )
                resp.raise_for_status()
            
            logger.debug(f"Uploaded: {local_path} -> {r2_key}")
            return True
            
        except Exception as e:
            logger.error(f"Upload failed {r2_key}: {e}")
            return False
    
    def upload_text(self, content: str, r2_key: str, content_type: Optional[str] = None) -> bool:
        """Загрузить текст в R2"""
        try:
            payload = {
                "content": content,
                "r2_key": r2_key,
                "content_type": content_type
            }
            self._request("post", "/api/storage/upload-text", json=payload)
            logger.debug(f"Uploaded text: {r2_key}")
            return True
        except Exception as e:
            logger.error(f"Upload text failed {r2_key}: {e}")
            return False
    
    def delete_object(self, r2_key: str) -> bool:
        """Удалить объект из R2"""
        try:
            self._request("delete", f"/api/storage/delete/{r2_key}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            raise
    
    def delete_objects_batch(self, keys: List[str]) -> tuple[List[str], List[str]]:
        """Удалить несколько объектов батчем"""
        payload = {"keys": keys}
        resp = self._request("post", "/api/storage/delete-batch", json=payload)
        data = resp.json()
        return data["deleted"], data["errors"]
    
    def delete_by_prefix(self, prefix: str) -> int:
        """Удалить все объекты с префиксом"""
        resp = self._request("delete", f"/api/storage/delete-prefix/{prefix}")
        return resp.json()["deleted_count"]
    
    def list_files(self, prefix: str) -> List[str]:
        """Список файлов по префиксу (только ключи)"""
        resp = self._request("get", f"/api/storage/list/{prefix}")
        return resp.json()
    
    def list_objects_with_metadata(self, prefix: str) -> List[Dict[str, Any]]:
        """Список файлов с метаданными"""
        resp = self._request("get", f"/api/storage/list-metadata/{prefix}")
        return resp.json()
