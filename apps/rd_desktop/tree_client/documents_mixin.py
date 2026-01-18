"""Mixin для работы с документами и файлами узлов"""
from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional

from apps.rd_desktop.tree_models import FileType, NodeFile, NodeType, TreeNode

logger = logging.getLogger(__name__)


class TreeDocumentsMixin:
    """Операции с документами и файлами узлов (node_files)"""

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
            attributes=attrs,
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
        """Добавить файл к узлу (PDF, аннотация, кроп и т.д.)"""
        file_id = str(uuid.uuid4())
        payload = {
            "id": file_id,
            "node_id": node_id,
            "file_type": file_type.value
            if isinstance(file_type, FileType)
            else file_type,
            "r2_key": r2_key,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "metadata": metadata or {},
        }
        resp = self._request("post", "/node_files", json=payload)
        return NodeFile.from_dict(resp.json()[0])

    def get_node_files(
        self, node_id: str, file_type: Optional[FileType] = None
    ) -> List[NodeFile]:
        """Получить все файлы узла (с фильтрацией по типу)"""
        path = f"/node_files?node_id=eq.{node_id}&order=created_at"
        if file_type:
            ft = file_type.value if isinstance(file_type, FileType) else file_type
            path += f"&file_type=eq.{ft}"
        resp = self._request("get", path)
        return [NodeFile.from_dict(r) for r in resp.json()]

    def get_node_file_by_r2_key(self, node_id: str, r2_key: str) -> Optional[NodeFile]:
        """Получить файл узла по r2_key"""
        resp = self._request(
            "get", f"/node_files?node_id=eq.{node_id}&r2_key=eq.{r2_key}"
        )
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

    def delete_node_file(
        self,
        file_id: str = None,
        node_id: str = None,
        file_type: str = None,
        r2_key: str = None,
    ) -> bool:
        """Удалить файл узла по ID или по комбинации node_id + file_type/r2_key

        Args:
            file_id: ID файла (если указан - удаляет по ID)
            node_id: ID узла (для фильтрации)
            file_type: Тип файла (annotation, pdf, etc)
            r2_key: R2 ключ файла

        Returns:
            True если удалено успешно
        """
        try:
            if file_id:
                self._request("delete", f"/node_files?id=eq.{file_id}")
            elif node_id:
                params = f"node_id=eq.{node_id}"
                if file_type:
                    params += f"&file_type=eq.{file_type}"
                if r2_key:
                    params += f"&r2_key=eq.{r2_key}"
                self._request("delete", f"/node_files?{params}")
            else:
                logger.warning("delete_node_file called without file_id or node_id")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to delete node file: {e}")
            return False

    def delete_jobs_by_node_id(self, node_id: str) -> int:
        """Удалить все jobs для узла (только записи БД, не файлы R2)"""
        try:
            resp = self._request("delete", f"/jobs?node_id=eq.{node_id}")
            data = resp.json()
            return len(data) if data else 0
        except Exception as e:
            logger.error(f"Failed to delete jobs for node {node_id}: {e}")
            return 0

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
        return self.add_node_file(
            node_id, file_type, r2_key, file_name, file_size, mime_type, metadata
        )
