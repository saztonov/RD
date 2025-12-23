"""Клиент для работы с деревом проектов в Supabase"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from httpx import Limits

logger = logging.getLogger(__name__)

# Глобальный пул соединений для Supabase
_tree_http_client: httpx.Client | None = None

def _get_tree_client() -> httpx.Client:
    """Получить или создать HTTP клиент с connection pooling"""
    global _tree_http_client
    if _tree_http_client is None:
        _tree_http_client = httpx.Client(
            limits=Limits(max_connections=10, max_keepalive_connections=5),
            timeout=30.0,
        )
    return _tree_http_client


class NodeType(str, Enum):
    PROJECT = "project"
    STAGE = "stage"
    SECTION = "section"
    TASK_FOLDER = "task_folder"
    DOCUMENT = "document"


class NodeStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


# Определяем какие дочерние типы могут быть у родительского
ALLOWED_CHILDREN: Dict[Optional[NodeType], List[NodeType]] = {
    None: [NodeType.PROJECT],
    NodeType.PROJECT: [NodeType.STAGE],
    NodeType.STAGE: [NodeType.SECTION],
    NodeType.SECTION: [NodeType.TASK_FOLDER],
    NodeType.TASK_FOLDER: [NodeType.DOCUMENT],
    NodeType.DOCUMENT: [],
}


class FileType(str, Enum):
    PDF = "pdf"
    ANNOTATION = "annotation"
    RESULT_MD = "result_md"
    RESULT_ZIP = "result_zip"
    CROP = "crop"
    IMAGE = "image"


@dataclass
class NodeFile:
    """Файл привязанный к узлу дерева"""
    id: str
    node_id: str
    file_type: FileType
    r2_key: str
    file_name: str
    file_size: int = 0
    mime_type: str = "application/octet-stream"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: dict) -> "NodeFile":
        return cls(
            id=data["id"],
            node_id=data["node_id"],
            file_type=FileType(data["file_type"]),
            r2_key=data["r2_key"],
            file_name=data["file_name"],
            file_size=data.get("file_size", 0),
            mime_type=data.get("mime_type", "application/octet-stream"),
            metadata=data.get("metadata") or {},
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")) if data.get("updated_at") else None,
        )


@dataclass
class TreeNode:
    """Узел дерева проектов"""
    id: str
    parent_id: Optional[str]
    client_id: str
    node_type: NodeType
    name: str
    code: Optional[str] = None
    version: int = 1
    status: NodeStatus = NodeStatus.ACTIVE
    attributes: Dict[str, Any] = field(default_factory=dict)
    sort_order: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    children: List["TreeNode"] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: dict) -> "TreeNode":
        return cls(
            id=data["id"],
            parent_id=data.get("parent_id"),
            client_id=data.get("client_id", ""),
            node_type=NodeType(data["node_type"]),
            name=data["name"],
            code=data.get("code"),
            version=data.get("version", 1),
            status=NodeStatus(data.get("status", "active")),
            attributes=data.get("attributes") or {},
            sort_order=data.get("sort_order", 0),
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")) if data.get("updated_at") else None,
        )
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "client_id": self.client_id,
            "node_type": self.node_type.value,
            "name": self.name,
            "code": self.code,
            "version": self.version,
            "status": self.status.value,
            "attributes": self.attributes,
            "sort_order": self.sort_order,
        }
    
    def get_allowed_child_types(self) -> List[NodeType]:
        return ALLOWED_CHILDREN.get(self.node_type, [])


@dataclass
class StageType:
    """Тип стадии"""
    id: int
    code: str
    name: str
    sort_order: int = 0


@dataclass
class SectionType:
    """Тип раздела"""
    id: int
    code: str
    name: str
    sort_order: int = 0


def _get_client_id() -> str:
    """Получить client_id"""
    from app.remote_ocr_client import _get_or_create_client_id
    return _get_or_create_client_id()


@dataclass
class TreeClient:
    """Клиент для работы с деревом проектов"""
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))
    client_id: str = field(default_factory=_get_client_id)
    timeout: float = 30.0
    
    def _headers(self) -> dict:
        return {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
    
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.supabase_url}/rest/v1{path}"
        client = _get_tree_client()
        resp = getattr(client, method)(url, headers=self._headers(), timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp
    
    def is_available(self) -> bool:
        """Проверить доступность Supabase"""
        if not self.supabase_url or not self.supabase_key:
            return False
        try:
            self._request("get", "/stage_types?select=id&limit=1")
            return True
        except Exception:
            return False
    
    # === Справочники ===
    
    def get_stage_types(self) -> List[StageType]:
        """Получить типы стадий"""
        resp = self._request("get", "/stage_types?order=sort_order")
        return [
            StageType(id=r["id"], code=r["code"], name=r["name"], sort_order=r.get("sort_order", 0))
            for r in resp.json()
        ]
    
    def get_section_types(self) -> List[SectionType]:
        """Получить типы разделов"""
        resp = self._request("get", "/section_types?order=sort_order")
        return [
            SectionType(id=r["id"], code=r["code"], name=r["name"], sort_order=r.get("sort_order", 0))
            for r in resp.json()
        ]
    
    # === CRUD для узлов ===
    
    def get_root_nodes(self) -> List[TreeNode]:
        """Получить корневые проекты (без parent_id) - все пользователи видят все проекты"""
        resp = self._request(
            "get", 
            "/tree_nodes?parent_id=is.null&order=sort_order,created_at"
        )
        return [TreeNode.from_dict(r) for r in resp.json()]
    
    def get_children(self, parent_id: str) -> List[TreeNode]:
        """Получить дочерние узлы (Lazy Loading)"""
        resp = self._request(
            "get",
            f"/tree_nodes?parent_id=eq.{parent_id}&order=sort_order,created_at"
        )
        return [TreeNode.from_dict(r) for r in resp.json()]
    
    def get_node(self, node_id: str) -> Optional[TreeNode]:
        """Получить узел по ID"""
        resp = self._request("get", f"/tree_nodes?id=eq.{node_id}")
        data = resp.json()
        return TreeNode.from_dict(data[0]) if data else None
    
    def create_node(
        self,
        node_type,
        name: str,
        parent_id: Optional[str] = None,
        code: Optional[str] = None,
        attributes: Optional[Dict] = None,
    ) -> TreeNode:
        """Создать новый узел"""
        # Конвертируем в строку для API
        if isinstance(node_type, NodeType):
            node_type_str = node_type.value
        else:
            node_type_str = str(node_type)
        
        node_id = str(uuid.uuid4())
        payload = {
            "id": node_id,
            "parent_id": parent_id,
            "client_id": self.client_id,
            "node_type": node_type_str,
            "name": name,
            "code": code,
            "attributes": attributes or {},
        }
        resp = self._request("post", "/tree_nodes", json=payload)
        return TreeNode.from_dict(resp.json()[0])
    
    def update_node(self, node_id: str, **fields) -> Optional[TreeNode]:
        """Обновить узел"""
        update_data = {}
        if "name" in fields:
            update_data["name"] = fields["name"]
        if "code" in fields:
            update_data["code"] = fields["code"]
        if "status" in fields:
            update_data["status"] = fields["status"].value if isinstance(fields["status"], NodeStatus) else fields["status"]
        if "attributes" in fields:
            update_data["attributes"] = fields["attributes"]
        if "sort_order" in fields:
            update_data["sort_order"] = fields["sort_order"]
        if "parent_id" in fields:
            update_data["parent_id"] = fields["parent_id"]
        if "version" in fields:
            update_data["version"] = fields["version"]
        
        if not update_data:
            return self.get_node(node_id)
        
        resp = self._request("patch", f"/tree_nodes?id=eq.{node_id}", json=update_data)
        data = resp.json()
        return TreeNode.from_dict(data[0]) if data else None
    
    def delete_node(self, node_id: str) -> bool:
        """Удалить узел (каскадно удалит дочерние)"""
        try:
            self._request("delete", f"/tree_nodes?id=eq.{node_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete node {node_id}: {e}")
            return False
    
    def move_node(self, node_id: str, new_parent_id: Optional[str]) -> bool:
        """Переместить узел к другому родителю"""
        # Валидация: нельзя переместить в себя или в своих потомков
        if new_parent_id:
            if node_id == new_parent_id:
                return False
            # Проверяем что new_parent не потомок node
            parent = self.get_node(new_parent_id)
            while parent and parent.parent_id:
                if parent.parent_id == node_id:
                    return False
                parent = self.get_node(parent.parent_id)
        
        return self.update_node(node_id, parent_id=new_parent_id) is not None
    
    # === Документы ===
    
    def add_document(
        self,
        parent_id: str,
        name: str,
        r2_key: str,
        file_size: int = 0,
        mime_type: str = "application/pdf",
        version: int = 1,
    ) -> TreeNode:
        """Добавить документ в папку заданий (файл хранится в R2)"""
        # Создаём узел документа (r2_key обязателен)
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
    
    def get_full_tree(self, max_depth: int = 2) -> List[TreeNode]:
        """Получить дерево с вложенностью до max_depth"""
        roots = self.get_root_nodes()
        
        def load_children(node: TreeNode, depth: int):
            if depth >= max_depth:
                return
            node.children = self.get_children(node.id)
            for child in node.children:
                load_children(child, depth + 1)
        
        for root in roots:
            load_children(root, 0)
        
        return roots
    
    # === Node Files (все файлы узла) ===
    
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
        """Добавить файл к узлу (PDF, аннотация, markdown, кроп и т.д.)"""
        file_id = str(uuid.uuid4())
        payload = {
            "id": file_id,
            "node_id": node_id,
            "file_type": file_type.value if isinstance(file_type, FileType) else file_type,
            "r2_key": r2_key,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "metadata": metadata or {},
        }
        resp = self._request("post", "/node_files", json=payload)
        return NodeFile.from_dict(resp.json()[0])
    
    def get_node_files(self, node_id: str, file_type: Optional[FileType] = None) -> List[NodeFile]:
        """Получить все файлы узла (с фильтрацией по типу)"""
        path = f"/node_files?node_id=eq.{node_id}&order=created_at"
        if file_type:
            ft = file_type.value if isinstance(file_type, FileType) else file_type
            path += f"&file_type=eq.{ft}"
        resp = self._request("get", path)
        return [NodeFile.from_dict(r) for r in resp.json()]
    
    def get_node_file_by_r2_key(self, node_id: str, r2_key: str) -> Optional[NodeFile]:
        """Получить файл узла по r2_key"""
        resp = self._request("get", f"/node_files?node_id=eq.{node_id}&r2_key=eq.{r2_key}")
        data = resp.json()
        return NodeFile.from_dict(data[0]) if data else None
    
    def update_node_file(self, file_id: str, **fields) -> Optional[NodeFile]:
        """Обновить файл узла"""
        update_data = {}
        if "file_size" in fields:
            update_data["file_size"] = fields["file_size"]
        if "metadata" in fields:
            update_data["metadata"] = fields["metadata"]
        if "file_name" in fields:
            update_data["file_name"] = fields["file_name"]
        if "r2_key" in fields:
            update_data["r2_key"] = fields["r2_key"]
        
        if not update_data:
            return None
        
        resp = self._request("patch", f"/node_files?id=eq.{file_id}", json=update_data)
        data = resp.json()
        return NodeFile.from_dict(data[0]) if data else None
    
    def delete_node_file(self, file_id: str) -> bool:
        """Удалить файл узла"""
        try:
            self._request("delete", f"/node_files?id=eq.{file_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete node file {file_id}: {e}")
            return False
    
    def upsert_node_file(
        self,
        node_id: str,
        file_type: FileType,
        r2_key: str,
        file_name: str,
        file_size: int = 0,
        mime_type: str = "application/octet-stream",
        metadata: Optional[Dict] = None,
    ) -> NodeFile:
        """Добавить или обновить файл узла (upsert по node_id + r2_key)"""
        existing = self.get_node_file_by_r2_key(node_id, r2_key)
        if existing:
            updated = self.update_node_file(
                existing.id,
                file_size=file_size,
                metadata=metadata or existing.metadata,
                file_name=file_name,
            )
            return updated if updated else existing
        return self.add_node_file(node_id, file_type, r2_key, file_name, file_size, mime_type, metadata)

