"""Mixin для управления доступом клиента к корневым проектам"""
from __future__ import annotations

from typing import List, Optional

from apps.rd_desktop.tree_client.base import _get_tree_client


class TreeClientAccessMixin:
    """Методы для управления доступом клиента к корневым проектам"""

    def get_client_root_ids(self, client_id: Optional[str] = None) -> Optional[List[str]]:
        """Получить список доступных корневых проектов для клиента.

        Returns:
            None если настройка не задана (т.е. показывать все),
            пустой список если фильтр задан, но проектов нет.
        """
        if client_id is None:
            from apps.rd_desktop.client_id import get_client_id
            client_id = get_client_id()

        if not client_id:
            return None

        key = self._get_root_access_key(client_id)
        resp = self._request("get", f"/app_settings?key=eq.{key}")
        data = resp.json()
        if not data:
            return None

        value = data[0].get("value")
        if isinstance(value, dict):
            root_ids = value.get("root_ids")
        elif isinstance(value, list):
            root_ids = value
        else:
            root_ids = []

        if root_ids is None:
            return []

        return [str(rid) for rid in root_ids if rid]

    def set_client_root_ids(self, root_ids: List[str], client_id: Optional[str] = None) -> None:
        """Сохранить доступные корневые проекты для клиента (upsert в app_settings)."""
        if client_id is None:
            from apps.rd_desktop.client_id import get_client_id
            client_id = get_client_id()

        if not client_id:
            raise ValueError("client_id is empty")

        key = self._get_root_access_key(client_id)

        # Уникализируем и сохраняем
        uniq_ids = []
        seen = set()
        for rid in root_ids:
            if rid and rid not in seen:
                uniq_ids.append(rid)
                seen.add(rid)

        payload = {"key": key, "value": {"root_ids": uniq_ids}}
        headers = self._headers()
        headers["Prefer"] = "resolution=merge-duplicates"

        url = f"{self.supabase_url}/rest/v1/app_settings"
        client = _get_tree_client()
        resp = client.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()

    def clear_client_root_ids(self, client_id: Optional[str] = None) -> None:
        """Сбросить настройку доступа (удалить запись app_settings)."""
        if client_id is None:
            from apps.rd_desktop.client_id import get_client_id
            client_id = get_client_id()

        if not client_id:
            return

        key = self._get_root_access_key(client_id)
        self._request("delete", f"/app_settings?key=eq.{key}")
