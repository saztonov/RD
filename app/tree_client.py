"""Клиент для работы с деревом проектов в Supabase"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from httpx import Limits

from app.tree_models import (
    ALLOWED_CHILDREN,
    FileType,
    NodeFile,
    NodeStatus,
    NodeType,
    SectionType,
    StageType,
    TreeNode,
)

# Реэкспорт для обратной совместимости
__all__ = [
    "NodeType",
    "NodeStatus",
    "FileType",
    "NodeFile",
    "TreeNode",
    "StageType",
    "SectionType",
    "TreeClient",
    "ALLOWED_CHILDREN",
]

logger = logging.getLogger(__name__)

# Глобальный пул соединений для Supabase
_tree_http_client: httpx.Client | None = None


def _get_tree_client() -> httpx.Client:
    """Получить или создать HTTP клиент с connection pooling"""
    global _tree_http_client
    if _tree_http_client is None:
        _tree_http_client = httpx.Client(
            limits=Limits(max_connections=10, max_keepalive_connections=5),
            timeout=30.0,
        )
    return _tree_http_client


def _get_client_id() -> str:
    """Получить client_id"""
    from app.remote_ocr_client import _get_or_create_client_id

    return _get_or_create_client_id()


@dataclass
class TreeClient:
    """Клиент для работы с деревом проектов"""

    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))
    client_id: str = field(default_factory=_get_client_id)
    timeout: float = 30.0

    def _headers(self) -> dict:
        return {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.supabase_url}/rest/v1{path}"
        try:
            client = _get_tree_client()
            resp = getattr(client, method)(
                url, headers=self._headers(), timeout=self.timeout, **kwargs
            )
            resp.raise_for_status()
            return resp
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, 
                httpx.TimeoutException, httpx.NetworkError) as e:
            logger.error(f"Сетевая ошибка при запросе к Supabase {method} {path}: {e}")
            raise

    def is_available(self) -> bool:
        """Проверить доступность Supabase"""
        if not self.supabase_url or not self.supabase_key:
            return False
        try:
            self._request("get", "/stage_types?select=id&limit=1")
            return True
        except Exception as e:
            logger.debug(f"Supabase недоступен: {e}")
            return False

    # === Справочники ===

    def get_stage_types(self) -> List[StageType]:
        """Получить типы стадий"""
        resp = self._request("get", "/stage_types?order=sort_order")
        return [
            StageType(
                id=r["id"],
                code=r["code"],
                name=r["name"],
                sort_order=r.get("sort_order", 0),
            )
            for r in resp.json()
        ]

    def get_section_types(self) -> List[SectionType]:
        """Получить типы разделов"""
        resp = self._request("get", "/section_types?order=sort_order")
        return [
            SectionType(
                id=r["id"],
                code=r["code"],
                name=r["name"],
                sort_order=r.get("sort_order", 0),
            )
            for r in resp.json()
        ]

    # === CRUD для узлов ===

    def get_root_nodes(self) -> List[TreeNode]:
        """Получить корневые проекты (без parent_id) - все пользователи видят все проекты"""
        resp = self._request(
            "get", "/tree_nodes?parent_id=is.null&order=sort_order,created_at"
        )
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_children(self, parent_id: str) -> List[TreeNode]:
        """Получить дочерние узлы (Lazy Loading)"""
        resp = self._request(
            "get", f"/tree_nodes?parent_id=eq.{parent_id}&order=sort_order,created_at"
        )
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_node(self, node_id: str) -> Optional[TreeNode]:
        """Получить узел по ID"""
        resp = self._request("get", f"/tree_nodes?id=eq.{node_id}")
        data = resp.json()
        return TreeNode.from_dict(data[0]) if data else None

    def get_pdf_status(self, node_id: str, use_cache: bool = True) -> tuple[str, str]:
        """
        Получить статус PDF документа (с кешем)

        Args:
            node_id: ID узла
            use_cache: Использовать кеш (по умолчанию True)

        Returns:
            Кортеж (статус, сообщение)
        """
        # Проверяем кеш
        if use_cache:
            from app.gui.pdf_status_cache import get_pdf_status_cache

            cache = get_pdf_status_cache()
            cached = cache.get(node_id)
            if cached:
                return cached

        # Загружаем из БД
        resp = self._request(
            "get", f"/tree_nodes?id=eq.{node_id}&select=pdf_status,pdf_status_message"
        )
        data = resp.json()
        if data:
            status = data[0].get("pdf_status", "unknown")
            message = data[0].get("pdf_status_message", "")

            # Сохраняем в кеш
            if use_cache:
                from app.gui.pdf_status_cache import get_pdf_status_cache

                cache = get_pdf_status_cache()
                cache.set(node_id, status, message)

            return status, message

        return "unknown", ""

    def get_pdf_statuses_batch(self, node_ids: list[str]) -> dict[str, tuple[str, str]]:
        """
        Получить статусы для нескольких документов одним запросом

        Returns:
            Словарь {node_id: (status, message)}
        """
        if not node_ids:
            return {}

        from app.gui.pdf_status_cache import get_pdf_status_cache

        cache = get_pdf_status_cache()
        result = {}
        uncached_ids = []

        # Проверяем кеш
        for node_id in node_ids:
            cached = cache.get(node_id)
            if cached:
                result[node_id] = cached
            else:
                uncached_ids.append(node_id)

        # Загружаем некешированные батчем
        if uncached_ids:
            # Формируем запрос с IN clause
            ids_str = ",".join(f'"{nid}"' for nid in uncached_ids)
            resp = self._request(
                "get",
                f"/tree_nodes?id=in.({ids_str})&select=id,pdf_status,pdf_status_message",
            )
            data = resp.json()

            for row in data:
                node_id = row["id"]
                status = row.get("pdf_status", "unknown")
                message = row.get("pdf_status_message", "")

                result[node_id] = (status, message)
                cache.set(node_id, status, message)

        return result

    def get_pdf_statuses_batch_fresh(self, node_ids: list[str]) -> dict[str, tuple[str, str]]:
        """
        Получить статусы для нескольких документов напрямую из БД (без кеша).
        Используется для автоматического обновления статусов.

        Returns:
            Словарь {node_id: (status, message)}
        """
        if not node_ids:
            return {}

        result = {}

        # Загружаем батчем напрямую из БД
        ids_str = ",".join(f'"{nid}"' for nid in node_ids)
        resp = self._request(
            "get",
            f"/tree_nodes?id=in.({ids_str})&select=id,pdf_status,pdf_status_message",
        )
        data = resp.json()

        for row in data:
            node_id = row["id"]
            status = row.get("pdf_status") or "unknown"
            message = row.get("pdf_status_message") or ""
            result[node_id] = (status, message)

        return result

    def update_pdf_status(self, node_id: str, status: str, message: str = None):
        """Обновить статус PDF документа и инвалидировать кеш"""
        try:
            self._request(
                "post",
                "/rpc/update_pdf_status",
                json={"p_node_id": node_id, "p_status": status, "p_message": message},
            )

            # Инвалидируем кеш для этого узла
            from app.gui.pdf_status_cache import get_pdf_status_cache

            cache = get_pdf_status_cache()
            cache.invalidate(node_id)

        except Exception as e:
            logger.error(f"Failed to update PDF status: {e}")

    def lock_document(self, node_id: str) -> bool:
        """Заблокировать документ от изменений"""
        try:
            self._request(
                "patch", f"/tree_nodes?id=eq.{node_id}", json={"is_locked": True}
            )
            return True
        except Exception as e:
            logger.error(f"Failed to lock document {node_id}: {e}")
            return False

    def unlock_document(self, node_id: str) -> bool:
        """Разблокировать документ"""
        try:
            self._request(
                "patch", f"/tree_nodes?id=eq.{node_id}", json={"is_locked": False}
            )
            return True
        except Exception as e:
            logger.error(f"Failed to unlock document {node_id}: {e}")
            return False

    def is_document_locked(self, node_id: str) -> bool:
        """Проверить заблокирован ли документ"""
        try:
            resp = self._request("get", f"/tree_nodes?id=eq.{node_id}&select=is_locked")
            data = resp.json()
            return data[0].get("is_locked", False) if data else False
        except Exception as e:
            logger.error(f"Failed to check lock status {node_id}: {e}")
            return False

    def create_node(
        self,
        node_type,
        name: str,
        parent_id: Optional[str] = None,
        code: Optional[str] = None,
        attributes: Optional[Dict] = None,
    ) -> TreeNode:
        """Создать новый узел"""
        # Конвертируем в строку для API
        if isinstance(node_type, NodeType):
            node_type_str = node_type.value
        else:
            node_type_str = str(node_type)

        node_id = str(uuid.uuid4())
        payload = {
            "id": node_id,
            "parent_id": parent_id,
            "client_id": self.client_id,
            "node_type": node_type_str,
            "name": name,
            "code": code,
            "attributes": attributes or {},
        }
        resp = self._request("post", "/tree_nodes", json=payload)
        return TreeNode.from_dict(resp.json()[0])

    def update_node(self, node_id: str, **fields) -> Optional[TreeNode]:
        """Обновить узел"""
        update_data = {}
        if "name" in fields:
            update_data["name"] = fields["name"]
        if "code" in fields:
            update_data["code"] = fields["code"]
        if "status" in fields:
            update_data["status"] = (
                fields["status"].value
                if isinstance(fields["status"], NodeStatus)
                else fields["status"]
            )
        if "attributes" in fields:
            update_data["attributes"] = fields["attributes"]
        if "sort_order" in fields:
            update_data["sort_order"] = fields["sort_order"]
        if "parent_id" in fields:
            update_data["parent_id"] = fields["parent_id"]
        if "version" in fields:
            update_data["version"] = fields["version"]

        if not update_data:
            return self.get_node(node_id)

        resp = self._request("patch", f"/tree_nodes?id=eq.{node_id}", json=update_data)
        data = resp.json()
        return TreeNode.from_dict(data[0]) if data else None

    def delete_node(self, node_id: str) -> bool:
        """Удалить узел (каскадно удалит дочерние)"""
        try:
            self._request("delete", f"/tree_nodes?id=eq.{node_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete node {node_id}: {e}")
            return False

    def move_node(self, node_id: str, new_parent_id: Optional[str]) -> bool:
        """Переместить узел к другому родителю"""
        # Валидация: нельзя переместить в себя или в своих потомков
        if new_parent_id:
            if node_id == new_parent_id:
                return False
            # Проверяем что new_parent не потомок node
            parent = self.get_node(new_parent_id)
            while parent and parent.parent_id:
                if parent.parent_id == node_id:
                    return False
                parent = self.get_node(parent.parent_id)

        return self.update_node(node_id, parent_id=new_parent_id) is not None

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

    def get_full_tree(self, max_depth: int = 2) -> List[TreeNode]:
        """Получить дерево с вложенностью до max_depth"""
        roots = self.get_root_nodes()

        def load_children(node: TreeNode, depth: int):
            if depth >= max_depth:
                return
            node.children = self.get_children(node.id)
            for child in node.children:
                load_children(child, depth + 1)

        for root in roots:
            load_children(root, 0)

        return roots

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

    def delete_node_file(self, file_id: str) -> bool:
        """Удалить файл узла"""
        try:
            self._request("delete", f"/node_files?id=eq.{file_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete node file {file_id}: {e}")
            return False

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

    # === Категории изображений ===

    def get_image_categories(self) -> List[Dict[str, Any]]:
        """Получить все категории изображений"""
        resp = self._request("get", "/image_categories?order=sort_order,name")
        return resp.json()

    def get_image_category(self, category_id: str) -> Optional[Dict[str, Any]]:
        """Получить категорию по ID"""
        resp = self._request("get", f"/image_categories?id=eq.{category_id}")
        data = resp.json()
        return data[0] if data else None

    def get_image_category_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Получить категорию по коду"""
        resp = self._request("get", f"/image_categories?code=eq.{code}")
        data = resp.json()
        return data[0] if data else None

    def get_default_image_category(self) -> Optional[Dict[str, Any]]:
        """Получить категорию по умолчанию"""
        resp = self._request("get", "/image_categories?is_default=eq.true&limit=1")
        data = resp.json()
        return data[0] if data else None

    def create_image_category(
        self,
        name: str,
        code: str,
        system_prompt: str = "",
        user_prompt: str = "",
        description: str = "",
        is_default: bool = False,
    ) -> Dict[str, Any]:
        """Создать новую категорию изображений"""
        cat_id = str(uuid.uuid4())
        payload = {
            "id": cat_id,
            "name": name,
            "code": code,
            "description": description,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "is_default": is_default,
        }
        # Если новая категория — default, снимаем флаг с остальных
        if is_default:
            self._request(
                "patch",
                "/image_categories?is_default=eq.true",
                json={"is_default": False},
            )

        resp = self._request("post", "/image_categories", json=payload)
        return resp.json()[0]

    def update_image_category(
        self, category_id: str, **fields
    ) -> Optional[Dict[str, Any]]:
        """Обновить категорию изображений"""
        update_data = {}
        for key in [
            "name",
            "code",
            "description",
            "system_prompt",
            "user_prompt",
            "is_default",
            "sort_order",
        ]:
            if key in fields:
                update_data[key] = fields[key]

        if not update_data:
            return self.get_image_category(category_id)

        # Если устанавливаем default — снимаем с других
        if update_data.get("is_default"):
            self._request(
                "patch",
                f"/image_categories?is_default=eq.true&id=neq.{category_id}",
                json={"is_default": False},
            )

        resp = self._request(
            "patch", f"/image_categories?id=eq.{category_id}", json=update_data
        )
        data = resp.json()
        return data[0] if data else None

    def delete_image_category(self, category_id: str) -> bool:
        """Удалить категорию изображений"""
        try:
            self._request("delete", f"/image_categories?id=eq.{category_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete image category {category_id}: {e}")
            return False

    # === Методы для работы с path (v2) ===

    def get_descendants(self, node_id: str) -> List[TreeNode]:
        """
        Получить всех потомков узла (используя materialized path).
        Быстрее чем рекурсивные запросы для больших деревьев.
        """
        node = self.get_node(node_id)
        if not node or not node.path:
            return []

        # Ищем все узлы чей path начинается с path узла + "."
        resp = self._request(
            "get",
            f"/tree_nodes?path=like.{node.path}.%&order=depth,sort_order",
        )
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_ancestors(self, node_id: str) -> List[TreeNode]:
        """
        Получить всех предков узла (от корня к узлу).
        Использует materialized path для эффективного запроса.
        """
        node = self.get_node(node_id)
        if not node or not node.path:
            return []

        # Парсим path и получаем ID предков
        path_parts = node.path.split(".")
        if len(path_parts) <= 1:
            return []  # Корневой узел, нет предков

        ancestor_ids = path_parts[:-1]  # Все кроме последнего (сам узел)

        # Запрашиваем одним батчем
        ids_str = ",".join(f'"{aid}"' for aid in ancestor_ids)
        resp = self._request("get", f"/tree_nodes?id=in.({ids_str})&order=depth")
        return [TreeNode.from_dict(r) for r in resp.json()]

    def get_subtree_stats(self, node_id: str) -> Dict[str, int]:
        """
        Получить статистику поддерева (используя денормализованные счётчики).
        Возвращает: folders_count, documents_count, files_count
        """
        node = self.get_node(node_id)
        if not node:
            return {"folders_count": 0, "documents_count": 0, "files_count": 0}

        # Используем path для подсчёта
        resp = self._request(
            "get",
            f"/tree_nodes?path=like.{node.path}%&select=node_type,files_count",
        )
        data = resp.json()

        folders = sum(1 for r in data if r["node_type"] == "folder")
        documents = sum(1 for r in data if r["node_type"] == "document")
        files = sum(r.get("files_count", 0) for r in data)

        return {
            "folders_count": folders,
            "documents_count": documents,
            "files_count": files,
        }

    def move_node_v2(self, node_id: str, new_parent_id: Optional[str]) -> bool:
        """
        Переместить узел (использует функцию БД move_tree_node для атомарного обновления path).
        """
        try:
            resp = self._request(
                "post",
                "/rpc/move_tree_node",
                json={"p_node_id": node_id, "p_new_parent_id": new_parent_id},
            )
            return resp.json() is True
        except Exception as e:
            logger.error(f"Failed to move node {node_id}: {e}")
            # Fallback на старый метод
            return self.move_node(node_id, new_parent_id)
