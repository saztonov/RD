"""Операции с node_files (связь с деревом проектов)"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Optional, Dict

from .storage_client import get_client

logger = logging.getLogger(__name__)


def get_node_file_by_type(node_id: str, file_type: str) -> Optional[Dict]:
    """Получить файл узла по типу (pdf, annotation и т.д.)"""
    client = get_client()
    result = client.table("node_files").select("*").eq("node_id", node_id).eq("file_type", file_type).limit(1).execute()
    return result.data[0] if result.data else None


def get_node_pdf_r2_key(node_id: str) -> Optional[str]:
    """Получить r2_key PDF для узла (из node_files или tree_nodes.attributes)"""
    # Сначала пробуем node_files
    pdf_file = get_node_file_by_type(node_id, "pdf")
    if pdf_file:
        return pdf_file.get("r2_key")
    
    # Fallback: tree_nodes.attributes.r2_key
    client = get_client()
    result = client.table("tree_nodes").select("attributes").eq("id", node_id).limit(1).execute()
    if result.data:
        attrs = result.data[0].get("attributes") or {}
        return attrs.get("r2_key")
    
    return None


def add_node_file(
    node_id: str,
    file_type: str,
    r2_key: str,
    file_name: str,
    file_size: int = 0,
    mime_type: str = "application/octet-stream",
    metadata: Optional[Dict] = None
) -> str:
    """Добавить файл к узлу дерева (upsert по node_id + r2_key)"""
    file_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    client = get_client()
    try:
        client.table("node_files").upsert({
            "id": file_id,
            "node_id": node_id,
            "file_type": file_type,
            "r2_key": r2_key,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now
        }, on_conflict="node_id,r2_key").execute()
        logger.debug(f"Node file registered: {file_type} -> {r2_key}")
        return file_id
    except Exception as e:
        logger.warning(f"Failed to add node file: {e}")
        return ""


def register_ocr_results_to_node(node_id: str, doc_name: str, work_dir) -> int:
    """Зарегистрировать все OCR результаты в node_files.
    
    Файлы загружены в папку исходного PDF (parent dir от pdf_r2_key)
    """
    if not node_id:
        return 0
    
    work_path = Path(work_dir)
    
    # Получаем r2_key исходного PDF и используем его родительскую папку
    pdf_r2_key = get_node_pdf_r2_key(node_id)
    if pdf_r2_key:
        tree_prefix = str(PurePosixPath(pdf_r2_key).parent)
    else:
        tree_prefix = f"tree_docs/{node_id}"
    
    registered = 0
    
    doc_stem = Path(doc_name).stem
    
    # result.md (переименован по имени документа)
    result_md = work_path / "result.md"
    if result_md.exists():
        md_filename = f"{doc_stem}.md"
        add_node_file(
            node_id, "result_md", f"{tree_prefix}/{md_filename}",
            md_filename, result_md.stat().st_size, "text/markdown"
        )
        registered += 1
    
    # annotation.json -> {doc_stem}_annotation.json
    annotation = work_path / "annotation.json"
    if annotation.exists():
        annotation_filename = f"{doc_stem}_annotation.json"
        add_node_file(
            node_id, "annotation", f"{tree_prefix}/{annotation_filename}",
            annotation_filename, annotation.stat().st_size, "application/json"
        )
        registered += 1
    
    # crops/
    crops_dir = work_path / "crops"
    if crops_dir.exists():
        for crop_file in crops_dir.iterdir():
            if crop_file.is_file() and crop_file.suffix.lower() == ".pdf":
                add_node_file(
                    node_id, "crop", f"{tree_prefix}/crops/{crop_file.name}",
                    crop_file.name, crop_file.stat().st_size, "application/pdf"
                )
                registered += 1
    
    logger.info(f"Registered {registered} OCR result files for node {node_id}")
    return registered

