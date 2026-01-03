"""Модели данных для дерева проектов"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


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
    CROP = "crop"
    IMAGE = "image"
    OCR_HTML = "ocr_html"
    RESULT_JSON = "result_json"
    RESULT_MD = "result_md"
    RESULT_ZIP = "result_zip"
    CROPS_FOLDER = "crops_folder"


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
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            if data.get("created_at")
            else None,
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
            if data.get("updated_at")
            else None,
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
    pdf_status: Optional[str] = None
    pdf_status_message: Optional[str] = None
    is_locked: bool = False

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
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            if data.get("created_at")
            else None,
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
            if data.get("updated_at")
            else None,
            pdf_status=data.get("pdf_status"),
            pdf_status_message=data.get("pdf_status_message"),
            is_locked=data.get("is_locked", False),
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
