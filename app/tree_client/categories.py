"""Операции с категориями изображений."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TreeCategoriesMixin:
    """Миксин для операций с категориями изображений"""

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
            "name", "code", "description", "system_prompt",
            "user_prompt", "is_default", "sort_order",
        ]:
            if key in fields:
                update_data[key] = fields[key]

        if not update_data:
            return self.get_image_category(category_id)

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
