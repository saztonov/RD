"""Функции для работы с узлами дерева проектов"""
import logging
import os
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)


def update_node_pdf_status(node_id: str):
    """
    Обновить статус PDF документа в БД
    
    Args:
        node_id: ID узла документа
    """
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
