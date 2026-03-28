"""Tree service — операции с деревом проектов.

Инкапсулирует бизнес-логику работы с TreeClient, R2Storage, AnnotationDBIO
для tree-related операций. GUI вызывает TreeService вместо прямого обращения.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TreeService:
    """Сервис операций с деревом проектов."""

    def lock_document(self, node_id: str) -> bool:
        """Заблокировать документ."""
        from app.tree_client import TreeClient
        client = TreeClient()
        return client.lock_document(node_id)

    def unlock_document(self, node_id: str) -> bool:
        """Разблокировать документ."""
        from app.tree_client import TreeClient
        client = TreeClient()
        return client.unlock_document(node_id)

    def get_ancestors(self, node_id: str) -> list:
        """Получить цепочку предков от корня к родителю."""
        from app.tree_client import TreeClient
        client = TreeClient()
        return client.get_ancestors(node_id)

    def get_node(self, node_id: str):
        """Получить узел по ID."""
        from app.tree_client import TreeClient
        client = TreeClient()
        return client.get_node(node_id)

    def get_node_files(self, node_id: str) -> list:
        """Получить файлы узла."""
        from app.tree_client import TreeClient
        client = TreeClient()
        return client.get_node_files(node_id)

    def delete_node_file(self, file_id: str) -> bool:
        """Удалить файл узла."""
        from app.tree_client import TreeClient
        client = TreeClient()
        return client.delete_node_file(file_id)

    def update_node(self, node_id: str, **kwargs) -> bool:
        """Обновить узел."""
        from app.tree_client import TreeClient
        client = TreeClient()
        return client.update_node(node_id, **kwargs)

    def copy_annotation(self, source_node_id: str) -> Optional[object]:
        """Скопировать аннотацию из узла."""
        from app.annotation_db import AnnotationDBIO
        try:
            return AnnotationDBIO.load_from_db(source_node_id)
        except Exception as e:
            logger.error(f"Ошибка копирования аннотации: {e}")
            return None

    def paste_annotation(self, document: object, target_node_id: str) -> bool:
        """Вставить аннотацию в узел."""
        from app.annotation_db import AnnotationDBIO
        try:
            return AnnotationDBIO.save_to_db(document, target_node_id)
        except Exception as e:
            logger.error(f"Ошибка вставки аннотации: {e}")
            return False

    def update_pdf_status(self, node_id: str, r2_key: str) -> tuple[str, str]:
        """Пересчитать PDF status для документа."""
        from app.services.document_service import get_document_service
        svc = get_document_service()
        return svc.update_pdf_status(node_id, r2_key)


# Singleton
_instance: Optional[TreeService] = None


def get_tree_service() -> TreeService:
    """Получить singleton TreeService."""
    global _instance
    if _instance is None:
        _instance = TreeService()
    return _instance
