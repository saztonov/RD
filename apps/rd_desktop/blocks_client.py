"""Клиент для работы с блоками в Supabase"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import httpx
from httpx import Limits

from rd_domain.models import Block, BlockSource, BlockType, ShapeType

logger = logging.getLogger(__name__)

# Глобальный пул соединений для Supabase
_blocks_http_client: httpx.Client | None = None


def _get_blocks_client() -> httpx.Client:
    """Получить или создать HTTP клиент с connection pooling"""
    global _blocks_http_client
    if _blocks_http_client is None:
        _blocks_http_client = httpx.Client(
            limits=Limits(max_connections=10, max_keepalive_connections=5),
            timeout=30.0,
        )
    return _blocks_http_client


@dataclass
class BlocksClient:
    """Клиент для CRUD операций с блоками в Supabase"""

    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))
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
            client = _get_blocks_client()
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
            self._request("get", "/blocks?select=id&limit=1")
            return True
        except Exception as e:
            logger.debug(f"Supabase blocks недоступен: {e}")
            return False

    # === Чтение ===

    def get_blocks_for_document(self, node_id: str) -> List[Block]:
        """Получить все блоки документа"""
        try:
            resp = self._request(
                "get",
                f"/blocks?node_id=eq.{node_id}&order=page_index,created_at"
            )
            return [self._row_to_block(r) for r in resp.json()]
        except Exception as e:
            logger.error(f"Failed to get blocks for document {node_id}: {e}")
            return []

    def get_blocks_for_page(self, node_id: str, page_index: int) -> List[Block]:
        """Получить блоки конкретной страницы"""
        try:
            resp = self._request(
                "get",
                f"/blocks?node_id=eq.{node_id}&page_index=eq.{page_index}&order=created_at"
            )
            return [self._row_to_block(r) for r in resp.json()]
        except Exception as e:
            logger.error(f"Failed to get blocks for page {page_index} of {node_id}: {e}")
            return []

    def get_block(self, block_id: str) -> Optional[Block]:
        """Получить блок по ID"""
        try:
            resp = self._request("get", f"/blocks?id=eq.{block_id}")
            data = resp.json()
            return self._row_to_block(data[0]) if data else None
        except Exception as e:
            logger.error(f"Failed to get block {block_id}: {e}")
            return None

    def has_blocks(self, node_id: str) -> bool:
        """Проверить есть ли блоки для документа"""
        try:
            resp = self._request(
                "get",
                f"/blocks?node_id=eq.{node_id}&select=id&limit=1"
            )
            return len(resp.json()) > 0
        except Exception:
            return False

    # === Запись ===

    def create_block(self, node_id: str, block: Block, client_id: str = None) -> Optional[Block]:
        """Создать новый блок"""
        try:
            payload = self._block_to_row(block, node_id, client_id)
            resp = self._request("post", "/blocks", json=payload)
            data = resp.json()
            return self._row_to_block(data[0]) if data else None
        except Exception as e:
            logger.error(f"Failed to create block: {e}")
            return None

    def update_block(self, block: Block) -> Optional[Block]:
        """Обновить блок"""
        try:
            payload = {
                "coords_px": list(block.coords_px),
                "coords_norm": list(block.coords_norm),
                "block_type": block.block_type.value,
                "source": block.source.value,
                "shape_type": block.shape_type.value,
                "polygon_points": [list(p) for p in block.polygon_points] if block.polygon_points else None,
                # OCR данные (ocr_text, prompt, hint, pdfplumber_text) хранятся только в annotation.json
                "linked_block_id": block.linked_block_id,
                "group_id": block.group_id,
                "group_name": block.group_name,
                "category_id": block.category_id,
                "category_code": block.category_code,
            }
            resp = self._request("patch", f"/blocks?id=eq.{block.id}", json=payload)
            data = resp.json()
            return self._row_to_block(data[0]) if data else None
        except Exception as e:
            logger.error(f"Failed to update block {block.id}: {e}")
            return None

    def delete_block(self, block_id: str) -> bool:
        """Удалить блок"""
        try:
            self._request("delete", f"/blocks?id=eq.{block_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete block {block_id}: {e}")
            return False

    def delete_blocks(self, block_ids: List[str]) -> int:
        """Удалить несколько блоков"""
        deleted = 0
        for block_id in block_ids:
            if self.delete_block(block_id):
                deleted += 1
        return deleted

    def delete_blocks_for_document(self, node_id: str) -> bool:
        """Удалить все блоки документа"""
        try:
            self._request("delete", f"/blocks?node_id=eq.{node_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete blocks for document {node_id}: {e}")
            return False

    # === Пакетные операции ===

    def sync_blocks(self, node_id: str, blocks: List[Block], client_id: str = None) -> bool:
        """
        Синхронизировать все блоки документа.

        Выполняет upsert блоков и удаляет отсутствующие.

        Args:
            node_id: ID документа
            blocks: список блоков для сохранения
            client_id: ID клиента

        Returns:
            True если успешно
        """
        try:
            # Получаем существующие ID
            existing_resp = self._request(
                "get",
                f"/blocks?node_id=eq.{node_id}&select=id"
            )
            existing_ids = {r["id"] for r in existing_resp.json()}

            # ID блоков для сохранения
            new_ids = {b.id for b in blocks}

            # Удаляем отсутствующие
            ids_to_delete = existing_ids - new_ids
            for block_id in ids_to_delete:
                self.delete_block(block_id)

            # Upsert блоков
            for block in blocks:
                payload = self._block_to_row(block, node_id, client_id)
                if block.id in existing_ids:
                    # Update
                    self._request("patch", f"/blocks?id=eq.{block.id}", json=payload)
                else:
                    # Insert
                    self._request("post", "/blocks", json=payload)

            logger.info(f"Synced {len(blocks)} blocks for {node_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync blocks for {node_id}: {e}")
            return False

    def upsert_blocks(self, node_id: str, blocks: List[Block], client_id: str = None) -> bool:
        """
        Upsert блоков (без удаления отсутствующих).

        Args:
            node_id: ID документа
            blocks: список блоков
            client_id: ID клиента

        Returns:
            True если успешно
        """
        try:
            for block in blocks:
                payload = self._block_to_row(block, node_id, client_id)
                # Upsert через POST с on_conflict
                headers = self._headers()
                headers["Prefer"] = "resolution=merge-duplicates,return=representation"
                url = f"{self.supabase_url}/rest/v1/blocks"
                client = _get_blocks_client()
                client.post(url, headers=headers, json=payload, timeout=self.timeout)

            return True
        except Exception as e:
            logger.error(f"Failed to upsert blocks for {node_id}: {e}")
            return False

    # === Конвертация ===

    def _block_to_row(self, block: Block, node_id: str, client_id: str = None) -> dict:
        """Конвертировать Block в словарь для БД"""
        return {
            "id": block.id,
            "node_id": node_id,
            "page_index": block.page_index,
            "coords_px": list(block.coords_px),
            "coords_norm": list(block.coords_norm),
            "block_type": block.block_type.value,
            "source": block.source.value,
            "shape_type": block.shape_type.value,
            "polygon_points": [list(p) for p in block.polygon_points] if block.polygon_points else None,
            # OCR данные (ocr_text, prompt, hint, pdfplumber_text) хранятся только в annotation.json
            "linked_block_id": block.linked_block_id,
            "group_id": block.group_id,
            "group_name": block.group_name,
            "category_id": block.category_id,
            "category_code": block.category_code,
            "client_id": client_id,
            "created_at": block.created_at,
        }

    def _row_to_block(self, row: dict) -> Block:
        """Конвертировать строку БД в Block"""
        # Обработка polygon_points
        polygon_points = None
        if row.get("polygon_points"):
            polygon_points = [tuple(p) for p in row["polygon_points"]]

        # Обработка block_type
        try:
            block_type = BlockType(row.get("block_type", "text"))
        except ValueError:
            block_type = BlockType.TEXT

        # Обработка source
        try:
            source = BlockSource(row.get("source", "user"))
        except ValueError:
            source = BlockSource.USER

        # Обработка shape_type
        try:
            shape_type = ShapeType(row.get("shape_type", "rectangle"))
        except ValueError:
            shape_type = ShapeType.RECTANGLE

        return Block(
            id=row["id"],
            page_index=row["page_index"],
            coords_px=tuple(row["coords_px"]),
            coords_norm=tuple(row["coords_norm"]),
            block_type=block_type,
            source=source,
            shape_type=shape_type,
            polygon_points=polygon_points,
            ocr_text=row.get("ocr_text"),
            prompt=row.get("prompt"),
            hint=row.get("hint"),
            pdfplumber_text=row.get("pdfplumber_text"),
            linked_block_id=row.get("linked_block_id"),
            group_id=row.get("group_id"),
            group_name=row.get("group_name"),
            category_id=row.get("category_id"),
            category_code=row.get("category_code"),
            created_at=row.get("created_at"),
        )
