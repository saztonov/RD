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


def get_node_info(node_id: str) -> Optional[Dict]:
    """Получить информацию о узле (parent_id, name, attributes)"""
    client = get_client()
    result = client.table("tree_nodes").select("id,parent_id,name,attributes").eq("id", node_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_node_full_path(node_id: str) -> str:
    """Получить полный путь узла (для логирования/отладки)"""
    parts = []
    current_id = node_id
    
    client = get_client()
    
    for _ in range(20):  # Защита от бесконечного цикла
        result = client.table("tree_nodes").select("name,parent_id").eq("id", current_id).limit(1).execute()
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
        result = client.table("tree_nodes").select("attributes").eq("id", node_id).limit(1).execute()
        if not result.data:
            return False
        
        attrs = result.data[0].get("attributes") or {}
        attrs["r2_key"] = r2_key
        
        client.table("tree_nodes").update({"attributes": attrs}).eq("id", node_id).execute()
        logger.info(f"Updated r2_key for node {node_id}: {r2_key}")
        return True
    except Exception as e:
        logger.error(f"Failed to update node r2_key: {e}")
        return False


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
    
    # result.json (переименован по имени документа)
    result_json = work_path / "result.json"
    if result_json.exists():
        json_filename = f"{doc_stem}.json"
        add_node_file(
            node_id, "result_json", f"{tree_prefix}/{json_filename}",
            json_filename, result_json.stat().st_size, "application/json"
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
    
    # ocr.html -> {doc_stem}_ocr.html
    ocr_html = work_path / "ocr.html"
    if ocr_html.exists():
        ocr_filename = f"{doc_stem}_ocr.html"
        add_node_file(
            node_id, "ocr_html", f"{tree_prefix}/{ocr_filename}",
            ocr_filename, ocr_html.stat().st_size, "text/html"
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


def update_node_pdf_status(node_id: str):
    """
    Обновить статус PDF документа в БД
    
    Args:
        node_id: ID узла документа
    """
    import os
    import sys
    from pathlib import Path
    
    # Добавляем корневую директорию проекта в путь если ещё не добавлено
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    try:
        from rd_core.r2_storage import R2Storage
        from rd_core.pdf_status import calculate_pdf_status
        import httpx
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        
        if not supabase_url or not supabase_key:
            logger.error("SUPABASE_URL or SUPABASE_KEY not set")
            return
        
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
        }
        
        # Получаем узел
        response = httpx.get(
            f"{supabase_url}/rest/v1/tree_nodes",
            params={"id": f"eq.{node_id}", "select": "id,attributes"},
            headers=headers,
            timeout=10.0
        )
        response.raise_for_status()
        nodes = response.json()
        
        if not nodes:
            logger.warning(f"Node {node_id} not found")
            return
        
        r2_key = nodes[0].get("attributes", {}).get("r2_key", "")
        if not r2_key:
            logger.warning(f"Node {node_id} has no r2_key")
            return
        
        # Вычисляем статус
        r2 = R2Storage()
        status, message = calculate_pdf_status(r2, node_id, r2_key, check_blocks=True)
        
        # Обновляем в БД
        rpc_response = httpx.post(
            f"{supabase_url}/rest/v1/rpc/update_pdf_status",
            json={
                "p_node_id": node_id,
                "p_status": status.value,
                "p_message": message
            },
            headers=headers,
            timeout=10.0
        )
        rpc_response.raise_for_status()
        
        logger.info(f"Updated PDF status for {node_id}: {status.value}")
        
    except Exception as e:
        logger.error(f"Failed to update node PDF status: {e}")
        raise
