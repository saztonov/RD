"""Операции с файлами узлов (node_files)"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from services.remote_ocr.server.storage_client import get_client

logger = logging.getLogger(__name__)


def get_node_files(node_id: str, file_type: Optional[str] = None) -> List[Dict]:
    """Получить файлы узла"""
    client = get_client()
    query = client.table("node_files").select("*").eq("node_id", node_id)

    if file_type:
        query = query.eq("file_type", file_type)

    result = query.order("created_at").execute()
    return result.data


def delete_node_file(file_id: str) -> bool:
    """Удалить файл узла"""
    try:
        client = get_client()
        client.table("node_files").delete().eq("id", file_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to delete node file {file_id}: {e}")
        return False


def get_node_file_by_type(node_id: str, file_type: str) -> Optional[Dict]:
    """Получить файл узла по типу (pdf, annotation и т.д.)"""
    client = get_client()
    result = (
        client.table("node_files")
        .select("*")
        .eq("node_id", node_id)
        .eq("file_type", file_type)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_node_pdf_r2_key(node_id: str) -> Optional[str]:
    """Получить r2_key PDF для узла (из node_files или tree_nodes.attributes)"""
    # Сначала пробуем node_files
    pdf_file = get_node_file_by_type(node_id, "pdf")
    if pdf_file:
        return pdf_file.get("r2_key")

    # Fallback: tree_nodes.attributes.r2_key
    client = get_client()
    result = (
        client.table("tree_nodes")
        .select("attributes")
        .eq("id", node_id)
        .limit(1)
        .execute()
    )
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
    metadata: Optional[Dict] = None,
) -> Dict:
    """Добавить файл к узлу дерева (upsert по node_id + r2_key)"""
    file_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    file_data = {
        "id": file_id,
        "node_id": node_id,
        "file_type": file_type,
        "r2_key": r2_key,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": mime_type,
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    }

    client = get_client()
    try:
        result = (
            client.table("node_files")
            .upsert(
                file_data,
                on_conflict="node_id,r2_key",
            )
            .execute()
        )
        logger.debug(f"Node file registered: {file_type} -> {r2_key}")
        return result.data[0] if result.data else file_data
    except Exception as e:
        logger.warning(f"Failed to add node file: {e}")
        return file_data
