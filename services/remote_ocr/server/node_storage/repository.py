"""CRUD операции с узлами дерева (tree_nodes)"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.remote_ocr.server.storage_client import get_client

logger = logging.getLogger(__name__)


def get_root_nodes() -> List[Any]:
    """Получить корневые узлы (проекты)"""
    client = get_client()
    result = (
        client.table("tree_nodes")
        .select("*")
        .is_("parent_id", "null")
        .order("sort_order,name")
        .execute()
    )
    return result.data


def get_node(node_id: str) -> Optional[Any]:
    """Получить узел по ID"""
    client = get_client()
    result = client.table("tree_nodes").select("*").eq("id", node_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_children(parent_id: str) -> List[Any]:
    """Получить дочерние узлы"""
    client = get_client()
    result = (
        client.table("tree_nodes")
        .select("*")
        .eq("parent_id", parent_id)
        .order("sort_order,name")
        .execute()
    )
    return result.data


def create_node(
    node_type: str,
    name: str,
    parent_id: Optional[str] = None,
    code: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> Any:
    """Создать новый узел"""
    node_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    client = get_client()
    result = (
        client.table("tree_nodes")
        .insert(
            {
                "id": node_id,
                "parent_id": parent_id,
                "node_type": node_type,
                "name": name,
                "code": code,
                "status": "active",
                "attributes": attributes or {},
                "sort_order": 0,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            }
        )
        .execute()
    )
    return result.data[0] if result.data else None


def update_node(node_id: str, **fields) -> Optional[Any]:
    """Обновить узел"""
    if not fields:
        return get_node(node_id)

    # Добавляем updated_at
    fields["updated_at"] = datetime.utcnow().isoformat()

    client = get_client()
    result = client.table("tree_nodes").update(fields).eq("id", node_id).execute()
    return result.data[0] if result.data else None


def delete_node(node_id: str) -> bool:
    """Удалить узел"""
    try:
        client = get_client()
        client.table("tree_nodes").delete().eq("id", node_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to delete node {node_id}: {e}")
        return False


def update_pdf_status(node_id: str, status: str, message: Optional[str] = None) -> bool:
    """Обновить статус PDF документа"""
    try:
        client = get_client()
        client.rpc(
            "update_pdf_status",
            {"p_node_id": node_id, "p_status": status, "p_message": message or ""},
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update PDF status for {node_id}: {e}")
        return False


def get_node_info(node_id: str) -> Optional[Dict]:
    """Получить информацию о узле (parent_id, name, attributes)"""
    client = get_client()
    result = (
        client.table("tree_nodes")
        .select("id,parent_id,name,attributes")
        .eq("id", node_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_node_full_path(node_id: str) -> str:
    """Получить полный путь узла (для логирования/отладки)"""
    parts = []
    current_id = node_id

    client = get_client()

    for _ in range(20):  # Защита от бесконечного цикла
        result = (
            client.table("tree_nodes")
            .select("name,parent_id")
            .eq("id", current_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            break

        node = result.data[0]
        parts.insert(0, node.get("name", ""))

        parent_id = node.get("parent_id")
        if not parent_id:
            break

        current_id = parent_id

    return " / ".join(parts)


def update_node_r2_key(node_id: str, r2_key: str) -> bool:
    """Обновить r2_key в attributes узла"""
    client = get_client()
    try:
        # Получаем текущие attributes
        result = (
            client.table("tree_nodes")
            .select("attributes")
            .eq("id", node_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return False

        attrs = result.data[0].get("attributes") or {}
        attrs["r2_key"] = r2_key

        client.table("tree_nodes").update({"attributes": attrs}).eq(
            "id", node_id
        ).execute()
        logger.info(f"Updated r2_key for node {node_id}: {r2_key}")
        return True
    except Exception as e:
        logger.error(f"Failed to update node r2_key: {e}")
        return False
