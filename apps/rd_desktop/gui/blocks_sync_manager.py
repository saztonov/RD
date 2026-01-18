"""Менеджер синхронизации блоков с Supabase Realtime"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from rd_domain.models import Block

logger = logging.getLogger(__name__)


class BlocksSyncManager(QObject):
    """
    Менеджер двусторонней синхронизации блоков между клиентом и Supabase.

    Обеспечивает:
    - Загрузку блоков из БД при открытии документа
    - Подписку на realtime изменения
    - Debounced отправку локальных изменений (300ms)
    - Обработку изменений от других клиентов

    Сигналы:
        blocks_loaded: (node_id, blocks) - блоки загружены из БД
        block_added_remote: (node_id, block) - блок добавлен другим клиентом
        block_updated_remote: (node_id, block) - блок обновлен другим клиентом
        block_deleted_remote: (node_id, block_id) - блок удален другим клиентом
        sync_error: (node_id, error) - ошибка синхронизации
    """

    # Сигналы для UI
    blocks_loaded = Signal(str, list)           # node_id, blocks
    block_added_remote = Signal(str, object)    # node_id, Block
    block_updated_remote = Signal(str, object)  # node_id, Block
    block_deleted_remote = Signal(str, str)     # node_id, block_id
    sync_error = Signal(str, str)               # node_id, error

    # Константы
    SYNC_DELAY_MS = 300  # Задержка перед отправкой изменений

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # Lazy imports
        self._blocks_client = None
        self._realtime_client = None

        # Executor для фоновых операций
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="blocks_sync")

        # Текущий документ
        self._current_node_id: Optional[str] = None
        self._current_client_id: Optional[str] = None

        # Локальный кеш версий для конфликт-резолюции
        self._block_versions: Dict[str, int] = {}

        # Очередь локальных изменений для debounce
        self._pending_changes: Dict[str, Block] = {}
        self._deleted_ids: Set[str] = set()

        # Таймер для debounced sync
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._flush_pending_changes)

        # Флаг игнорирования собственных изменений
        self._syncing_ids: Set[str] = set()

    def _get_blocks_client(self):
        """Lazy initialization of BlocksClient"""
        if self._blocks_client is None:
            from apps.rd_desktop.blocks_client import BlocksClient
            self._blocks_client = BlocksClient()
        return self._blocks_client

    def _get_realtime_client(self):
        """Lazy initialization of RealtimeClient"""
        if self._realtime_client is None:
            from apps.rd_desktop.supabase_realtime import SupabaseRealtimeClient
            self._realtime_client = SupabaseRealtimeClient(self)
            self._realtime_client.block_changed.connect(self._on_remote_block_change)
            self._realtime_client.connect_to_realtime()
        return self._realtime_client

    def set_document(self, node_id: Optional[str], client_id: str = None):
        """
        Установить текущий документ для синхронизации.

        Args:
            node_id: ID документа (или None для отключения)
            client_id: ID клиента
        """
        # Отписываемся от предыдущего
        if self._current_node_id:
            realtime = self._get_realtime_client()
            realtime.unsubscribe_from_blocks(self._current_node_id)

        # Очищаем состояние
        self._current_node_id = node_id
        self._current_client_id = client_id
        self._block_versions.clear()
        self._pending_changes.clear()
        self._deleted_ids.clear()
        self._syncing_ids.clear()

        # Подписываемся на новый
        if node_id:
            realtime = self._get_realtime_client()
            realtime.subscribe_to_blocks(node_id)
            logger.info(f"BlocksSyncManager: set document {node_id}")

    def load_blocks(self, node_id: str) -> List[Block]:
        """
        Загрузить блоки из БД (синхронно).

        Args:
            node_id: ID документа

        Returns:
            Список блоков
        """
        try:
            client = self._get_blocks_client()
            blocks = client.get_blocks_for_document(node_id)

            # Кешируем версии
            for block in blocks:
                self._block_versions[block.id] = 1

            logger.info(f"Loaded {len(blocks)} blocks from DB for {node_id}")
            return blocks

        except Exception as e:
            logger.error(f"Failed to load blocks for {node_id}: {e}")
            self.sync_error.emit(node_id, str(e))
            return []

    def load_blocks_async(self, node_id: str):
        """
        Загрузить блоки асинхронно.

        Args:
            node_id: ID документа

        Эмитит blocks_loaded когда готово.
        """
        def _load():
            client = self._get_blocks_client()
            return client.get_blocks_for_document(node_id)

        future = self._executor.submit(_load)
        future.add_done_callback(
            lambda f: self._on_blocks_loaded(node_id, f)
        )

    def _on_blocks_loaded(self, node_id: str, future):
        """Callback после загрузки блоков."""
        try:
            blocks = future.result()
            for block in blocks:
                self._block_versions[block.id] = 1
            self.blocks_loaded.emit(node_id, blocks)
        except Exception as e:
            self.sync_error.emit(node_id, str(e))

    def has_blocks(self, node_id: str) -> bool:
        """Проверить есть ли блоки в БД."""
        try:
            client = self._get_blocks_client()
            return client.has_blocks(node_id)
        except Exception:
            return False

    # === Локальные изменения ===

    def mark_block_changed(self, block: Block):
        """
        Пометить блок как измененный (для debounced sync).

        Args:
            block: измененный блок
        """
        if not self._current_node_id:
            return

        self._pending_changes[block.id] = block
        self._deleted_ids.discard(block.id)
        self._schedule_sync()

    def mark_block_deleted(self, block_id: str):
        """
        Пометить блок как удаленный.

        Args:
            block_id: ID удаленного блока
        """
        if not self._current_node_id:
            return

        self._pending_changes.pop(block_id, None)
        self._deleted_ids.add(block_id)
        self._schedule_sync()

    def mark_blocks_changed(self, blocks: List[Block]):
        """
        Пометить несколько блоков как измененные.

        Args:
            blocks: список измененных блоков
        """
        if not self._current_node_id:
            return

        for block in blocks:
            self._pending_changes[block.id] = block
            self._deleted_ids.discard(block.id)

        self._schedule_sync()

    def _schedule_sync(self):
        """Запланировать sync с debounce."""
        if self._sync_timer.isActive():
            self._sync_timer.stop()
        self._sync_timer.start(self.SYNC_DELAY_MS)

    @Slot()
    def _flush_pending_changes(self):
        """Отправить накопленные изменения в БД."""
        if not self._current_node_id:
            return

        changes = list(self._pending_changes.values())
        deletes = list(self._deleted_ids)

        self._pending_changes.clear()
        self._deleted_ids.clear()

        if not changes and not deletes:
            return

        # Помечаем что это наши изменения (для игнорирования realtime)
        for block in changes:
            self._syncing_ids.add(block.id)
        for block_id in deletes:
            self._syncing_ids.add(block_id)

        # Асинхронная отправка
        self._executor.submit(
            self._sync_changes,
            self._current_node_id,
            changes,
            deletes
        )

    def _sync_changes(self, node_id: str, changes: List[Block], deletes: List[str]):
        """Фоновая синхронизация изменений."""
        try:
            client = self._get_blocks_client()

            # Удаляем
            for block_id in deletes:
                client.delete_block(block_id)
                self._block_versions.pop(block_id, None)
                logger.debug(f"Deleted block {block_id}")

            # Обновляем/создаем
            for block in changes:
                if block.id in self._block_versions:
                    client.update_block(block)
                    logger.debug(f"Updated block {block.id}")
                else:
                    client.create_block(node_id, block, self._current_client_id)
                    logger.debug(f"Created block {block.id}")

                self._block_versions[block.id] = self._block_versions.get(block.id, 0) + 1

            logger.info(f"Synced {len(changes)} changes, {len(deletes)} deletes for {node_id}")

        except Exception as e:
            logger.error(f"Sync changes failed: {e}")
            self.sync_error.emit(node_id, str(e))

        finally:
            # Очищаем флаги синхронизации
            for block in changes:
                self._syncing_ids.discard(block.id)
            for block_id in deletes:
                self._syncing_ids.discard(block_id)

    def force_sync(self):
        """Принудительная синхронизация."""
        self._sync_timer.stop()
        self._flush_pending_changes()

    # === Удаленные изменения ===

    @Slot(dict)
    def _on_remote_block_change(self, data: dict):
        """Обработка изменения блока от другого клиента."""
        if not self._current_node_id:
            return

        change_type = data.get("type")
        record = data.get("record", {})
        old_record = data.get("old_record", {})
        node_id = data.get("node_id")

        # Проверяем что это наш документ
        if node_id != self._current_node_id:
            return

        block_id = record.get("id") or old_record.get("id")

        # Игнорируем собственные изменения
        if block_id in self._syncing_ids:
            logger.debug(f"Ignoring own change for block {block_id}")
            return

        # Игнорируем если блок в pending changes
        if block_id in self._pending_changes:
            logger.debug(f"Ignoring remote change for pending block {block_id}")
            return

        if change_type == "DELETE":
            self._block_versions.pop(block_id, None)
            self.block_deleted_remote.emit(node_id, block_id)
            logger.info(f"Remote block deleted: {block_id}")

        elif change_type in ("INSERT", "UPDATE"):
            client = self._get_blocks_client()
            block = client._row_to_block(record)

            remote_version = record.get("version", 1)
            local_version = self._block_versions.get(block_id, 0)

            # Конфликт-резолюция: последний побеждает
            if remote_version >= local_version:
                self._block_versions[block_id] = remote_version

                if change_type == "INSERT":
                    self.block_added_remote.emit(node_id, block)
                    logger.info(f"Remote block added: {block_id}")
                else:
                    self.block_updated_remote.emit(node_id, block)
                    logger.info(f"Remote block updated: {block_id}")

    def sync_all_blocks(self, blocks: List[Block]) -> bool:
        """
        Синхронизировать все блоки документа (полная перезапись).

        Args:
            blocks: полный список блоков

        Returns:
            True если успешно
        """
        if not self._current_node_id:
            return False

        try:
            client = self._get_blocks_client()
            success = client.sync_blocks(
                self._current_node_id,
                blocks,
                self._current_client_id
            )

            if success:
                self._block_versions.clear()
                for block in blocks:
                    self._block_versions[block.id] = 1

            return success

        except Exception as e:
            logger.error(f"sync_all_blocks failed: {e}")
            return False

    def cleanup(self):
        """Очистка при закрытии."""
        if self._current_node_id and self._realtime_client:
            self._realtime_client.unsubscribe_from_blocks(self._current_node_id)

        self._sync_timer.stop()
        self._executor.shutdown(wait=False)
        logger.info("BlocksSyncManager cleanup complete")
