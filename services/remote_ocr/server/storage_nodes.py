"""Операции с node_files и tree_nodes (связь с деревом проектов)"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from .storage_client import get_client

logger = logging.getLogger(__name__)


# ===== CRUD операции с узлами дерева =====


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


# ===== Вспомогательные функции =====


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


def register_ocr_results_to_node(node_id: str, doc_name: str, work_dir) -> int:
    """Зарегистрировать все OCR результаты в node_files.

    Файлы загружены в папку исходного PDF (parent dir от pdf_r2_key).
    Кропы сохраняются с метаданными блоков (block_id, page_index, coords, block_type).
    """
    if not node_id:
        return 0

    work_path = Path(work_dir)
    now = datetime.utcnow().isoformat()

    # Получаем r2_key исходного PDF и используем его родительскую папку
    pdf_r2_key = get_node_pdf_r2_key(node_id)
    if pdf_r2_key:
        tree_prefix = str(PurePosixPath(pdf_r2_key).parent)
    else:
        tree_prefix = f"tree_docs/{node_id}"

    registered = 0

    doc_stem = Path(doc_name).stem

    # Загружаем annotation.json для получения метаданных блоков
    blocks_by_id: Dict[str, dict] = {}
    annotation_path = work_path / "annotation.json"
    if annotation_path.exists():
        try:
            with open(annotation_path, "r", encoding="utf-8") as f:
                ann = json.load(f)
            for page in ann.get("pages", []):
                for blk in page.get("blocks", []):
                    blocks_by_id[blk["id"]] = blk
        except Exception as e:
            logger.warning(f"Failed to load annotation.json for metadata: {e}")

    # result.json -> {doc_stem}_result.json
    result_json = work_path / "result.json"
    if result_json.exists():
        json_filename = f"{doc_stem}_result.json"
        add_node_file(
            node_id,
            "result_json",
            f"{tree_prefix}/{json_filename}",
            json_filename,
            result_json.stat().st_size,
            "application/json",
        )
        registered += 1

    # annotation.json -> {doc_stem}_annotation.json
    if annotation_path.exists():
        annotation_filename = f"{doc_stem}_annotation.json"
        add_node_file(
            node_id,
            "annotation",
            f"{tree_prefix}/{annotation_filename}",
            annotation_filename,
            annotation_path.stat().st_size,
            "application/json",
        )
        registered += 1

    # ocr_result.html -> {doc_stem}_ocr.html
    ocr_html = work_path / "ocr_result.html"
    if ocr_html.exists():
        ocr_filename = f"{doc_stem}_ocr.html"
        add_node_file(
            node_id,
            "ocr_html",
            f"{tree_prefix}/{ocr_filename}",
            ocr_filename,
            ocr_html.stat().st_size,
            "text/html",
        )
        registered += 1

    # document.md -> {doc_stem}_document.md
    document_md = work_path / "document.md"
    if document_md.exists():
        md_filename = f"{doc_stem}_document.md"
        add_node_file(
            node_id,
            "document_md",
            f"{tree_prefix}/{md_filename}",
            md_filename,
            document_md.stat().st_size,
            "text/markdown",
        )
        registered += 1

    # Собираем все кропы из crops/ и crops_final/
    all_crop_files: List[Path] = []
    for crops_subdir in ["crops", "crops_final"]:
        crops_dir = work_path / crops_subdir
        if crops_dir.exists():
            for crop_file in crops_dir.iterdir():
                if crop_file.is_file() and crop_file.suffix.lower() == ".pdf":
                    # Избегаем дубликатов (проверяем по имени файла)
                    if not any(c.name == crop_file.name for c in all_crop_files):
                        all_crop_files.append(crop_file)

    # Регистрируем папку кропов как сущность
    if all_crop_files:
        add_node_file(
            node_id,
            "crops_folder",
            f"{tree_prefix}/crops/",
            "crops",
            0,
            "inode/directory",
            metadata={"crops_count": len(all_crop_files), "created_at": now},
        )
        registered += 1

    # Регистрируем каждый кроп с метаданными блока
    for crop_file in all_crop_files:
        block_id = crop_file.stem  # block_id = имя файла без расширения
        block_data = blocks_by_id.get(block_id, {})

        add_node_file(
            node_id,
            "crop",
            f"{tree_prefix}/crops/{crop_file.name}",
            crop_file.name,
            crop_file.stat().st_size,
            "application/pdf",
            metadata={
                "block_id": block_id,
                "page_index": block_data.get("page_index"),
                "coords_norm": block_data.get("coords_norm"),
                "block_type": block_data.get("block_type"),
            },
        )
        registered += 1

    logger.info(
        f"Registered {registered} OCR result files for node {node_id} ({len(all_crop_files)} crops)"
    )
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
        import httpx

        from rd_core.pdf_status import calculate_pdf_status
        from rd_core.r2_storage import R2Storage

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
            timeout=10.0,
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
            json={"p_node_id": node_id, "p_status": status.value, "p_message": message},
            headers=headers,
            timeout=10.0,
        )
        rpc_response.raise_for_status()

        logger.info(f"Updated PDF status for {node_id}: {status.value}")

    except Exception as e:
        logger.error(f"Failed to update node PDF status: {e}")
        raise
