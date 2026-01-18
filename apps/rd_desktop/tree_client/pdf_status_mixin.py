"""Mixin для работы с PDF статусами и блокировками документов"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TreePdfStatusMixin:
    """Операции со статусами PDF и блокировками документов"""

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
            from apps.rd_desktop.gui.pdf_status_cache import get_pdf_status_cache
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
                from apps.rd_desktop.gui.pdf_status_cache import get_pdf_status_cache
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

        from apps.rd_desktop.gui.pdf_status_cache import get_pdf_status_cache
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
            from apps.rd_desktop.gui.pdf_status_cache import get_pdf_status_cache
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
