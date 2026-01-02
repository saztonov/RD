"""Модели данных для хранилища задач OCR"""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class JobFile:
    id: str
    job_id: str
    file_type: str  # pdf|blocks|annotation|result_md|result_zip|crop
    r2_key: str
    file_name: str
    file_size: int
    created_at: str


@dataclass
class JobSettings:
    job_id: str
    text_model: str = ""
    table_model: str = ""
    image_model: str = ""
    stamp_model: str = ""


@dataclass
class Job:
    id: str
    client_id: str
    document_id: str
    document_name: str
    task_name: str
    status: str  # draft|queued|processing|done|error|paused
    progress: float
    created_at: str
    updated_at: str
    error_message: Optional[str]
    engine: str
    r2_prefix: str
    node_id: Optional[str] = None  # ID узла дерева (для связи с деревом проектов)
    # Вложенные данные (опционально загружаются)
    files: List[JobFile] = field(default_factory=list)
    settings: Optional[JobSettings] = None



