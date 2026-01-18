"""Авто-сохранение аннотаций через BlocksSyncManager и fallback через кеш"""
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer

from rd_domain.annotation import AnnotationIO

logger = logging.getLogger(__name__)


def get_annotation_path(pdf_path: str) -> Path:
    """Путь к annotation.json для PDF файла"""
    p = Path(pdf_path)
    return p.parent / f"{p.stem}_annotation.json"


def get_annotation_r2_key(pdf_r2_key: str) -> str:
    """R2 ключ для annotation.json"""
    from pathlib import PurePosixPath
    p = PurePosixPath(pdf_r2_key)
    return str(p.parent / f"{p.stem}_annotation.json")


class FileAutoSaveMixin:
    """Миксин для авто-сохранения аннотаций через BlocksSyncManager и fallback кеш"""

    _current_r2_key: str = ""
    _current_node_id: str = ""
    _annotation_synced: bool = False
    _blocks_sync_manager = None
    _use_db_sync: bool = True  # Использовать синхронизацию через БД

    def _init_blocks_sync(self):
        """Инициализация менеджера синхронизации блоков"""
        if self._blocks_sync_manager is not None:
            return

        from apps.rd_desktop.gui.blocks_sync_manager import BlocksSyncManager

        self._blocks_sync_manager = BlocksSyncManager(self)

        # Подключаем сигналы для обновления UI
        self._blocks_sync_manager.block_added_remote.connect(self._on_remote_block_added)
        self._blocks_sync_manager.block_updated_remote.connect(self._on_remote_block_updated)
        self._blocks_sync_manager.block_deleted_remote.connect(self._on_remote_block_deleted)
        self._blocks_sync_manager.sync_error.connect(self._on_blocks_sync_error)

        logger.info("BlocksSyncManager initialized")

    def _set_document_for_sync(self, node_id: str):
        """Установить документ для синхронизации блоков"""
        if not self._use_db_sync:
            return

        if self._blocks_sync_manager is None:
            self._init_blocks_sync()

        from apps.rd_desktop.client_id import get_client_id
        client_id = get_client_id()
        self._blocks_sync_manager.set_document(node_id, client_id)

    def _on_remote_block_added(self, node_id: str, block):
        """Обработка добавления блока другим клиентом"""
        if node_id != self._current_node_id:
            return

        if not self.annotation_document:
            return

        # Добавляем блок в annotation_document
        if block.page_index < len(self.annotation_document.pages):
            page = self.annotation_document.pages[block.page_index]
            # Проверяем что блока еще нет
            if not any(b.id == block.id for b in page.blocks):
                page.blocks.append(block)
                # Обновляем UI если эта страница открыта
                if hasattr(self, 'current_page') and self.current_page == block.page_index:
                    if hasattr(self, 'page_viewer'):
                        # Используем инкрементальное добавление
                        self.page_viewer.add_block_visual(block)
                    if hasattr(self, 'blocks_tree_manager') and self.blocks_tree_manager:
                        self.blocks_tree_manager.update_blocks_tree()
                self._show_remote_change_toast("Добавлен блок")
                logger.info(f"Remote block added: {block.id}")

    def _on_remote_block_updated(self, node_id: str, block):
        """Обработка обновления блока другим клиентом"""
        if node_id != self._current_node_id:
            return

        if not self.annotation_document:
            return

        if block.page_index < len(self.annotation_document.pages):
            page = self.annotation_document.pages[block.page_index]
            # Находим и обновляем блок
            for i, b in enumerate(page.blocks):
                if b.id == block.id:
                    page.blocks[i] = block
                    break

            if hasattr(self, 'current_page') and self.current_page == block.page_index:
                if hasattr(self, 'page_viewer'):
                    # Используем инкрементальное обновление
                    self.page_viewer.update_block_visual(block)
                if hasattr(self, 'blocks_tree_manager') and self.blocks_tree_manager:
                    self.blocks_tree_manager.update_blocks_tree()
            self._show_remote_change_toast("Обновлен блок")
            logger.info(f"Remote block updated: {block.id}")

    def _on_remote_block_deleted(self, node_id: str, block_id: str):
        """Обработка удаления блока другим клиентом"""
        if node_id != self._current_node_id:
            return

        if not self.annotation_document:
            return

        for page in self.annotation_document.pages:
            for i, block in enumerate(page.blocks):
                if block.id == block_id:
                    page_index = page.page_number
                    del page.blocks[i]
                    if hasattr(self, 'current_page') and self.current_page == page_index:
                        if hasattr(self, 'page_viewer'):
                            # Используем инкрементальное удаление
                            self.page_viewer.remove_block_visual(block_id)
                        if hasattr(self, 'blocks_tree_manager') and self.blocks_tree_manager:
                            self.blocks_tree_manager.update_blocks_tree()
                    self._show_remote_change_toast("Удален блок")
                    logger.info(f"Remote block deleted: {block_id}")
                    return

    def _show_remote_change_toast(self, message: str):
        """Показать уведомление об изменении от другого клиента"""
        try:
            from apps.rd_desktop.gui.toast import show_toast
            show_toast(self, f"{message} (другим пользователем)", duration=2000)
        except Exception:
            pass

    def _on_blocks_sync_error(self, node_id: str, error: str):
        """Обработка ошибки синхронизации блоков"""
        logger.error(f"Blocks sync error for {node_id}: {error}")

    def _auto_save_annotation(self):
        """Авто-сохранение разметки через BlocksSyncManager или кеш"""
        if not self.annotation_document or not self._current_pdf_path:
            return

        if not self._current_node_id:
            return

        # Используем синхронизацию через БД если доступна
        if self._use_db_sync and self._blocks_sync_manager:
            # Собираем все блоки документа
            all_blocks = []
            for page in self.annotation_document.pages:
                all_blocks.extend(page.blocks)

            # Помечаем для синхронизации (debounced)
            self._blocks_sync_manager.mark_blocks_changed(all_blocks)
            return

        # Fallback на старый кеш аннотаций
        from apps.rd_desktop.gui.annotation_cache import get_annotation_cache

        cache = get_annotation_cache()

        # Обновляем кеш (мгновенно)
        cache.set(
            self._current_node_id,
            self.annotation_document,
            self._current_pdf_path,
            self._current_r2_key,
            str(get_annotation_path(self._current_pdf_path))
        )

        # Помечаем как измененную (запустит отложенное сохранение)
        cache.mark_dirty(self._current_node_id)

    def _flush_pending_save(self):
        """Принудительно синхронизировать"""
        if not self._current_node_id:
            return

        # Используем синхронизацию через БД если доступна
        if self._use_db_sync and self._blocks_sync_manager:
            self._blocks_sync_manager.force_sync()
            return

        # Fallback на старый кеш
        from apps.rd_desktop.gui.annotation_cache import get_annotation_cache
        cache = get_annotation_cache()
        cache.force_sync(self._current_node_id)
    
    def _setup_annotation_cache_signals(self):
        """Подключить сигналы кеша аннотаций"""
        from apps.rd_desktop.gui.annotation_cache import get_annotation_cache
        
        cache = get_annotation_cache()
        cache.synced.connect(self._on_annotation_synced)
        cache.sync_failed.connect(self._on_annotation_sync_failed)
    
    def _on_annotation_synced(self, node_id: str):
        """Обработчик успешной синхронизации"""
        if node_id == self._current_node_id:
            self._annotation_synced = True
            logger.info(f"Annotation synced for node {node_id}")
            
            # Обновляем иконку в дереве
            QTimer.singleShot(0, lambda: self._update_tree_annotation_icon(node_id))
    
    def _on_annotation_sync_failed(self, node_id: str, error: str):
        """Обработчик ошибки синхронизации"""
        logger.error(f"Annotation sync failed for {node_id}: {error}")

    def _update_tree_annotation_icon(self, node_id: str):
        """Обновить иконку аннотации в дереве"""
        if not hasattr(self, "project_tree") or not self.project_tree:
            return

        try:
            from PySide6.QtCore import Qt
            from apps.rd_desktop.tree_client import TreeClient
            from rd_pipeline.pdf import calculate_pdf_status
            from rd_adapters.storage import R2SyncStorage as R2Storage

            item = self.project_tree._node_map.get(node_id)
            if item:
                node = item.data(0, Qt.UserRole)
                if node and hasattr(node, "attributes"):
                    node.attributes["has_annotation"] = True
                    item.setData(0, Qt.UserRole, node)

                    r2_key = node.attributes.get("r2_key", "")
                    if r2_key:
                        client = TreeClient()
                        r2 = R2Storage()
                        status, message = calculate_pdf_status(r2, node_id, r2_key)
                        client.update_pdf_status(node_id, status.value, message)

                        item = self.project_tree._node_map.get(node_id)
                        if item and node.node_type.value == "document":
                            node.pdf_status = status.value
                            node.pdf_status_message = message

                            from apps.rd_desktop.gui.tree_node_operations import NODE_ICONS

                            icon = NODE_ICONS.get(node.node_type, "📄")
                            status_icon = self.project_tree._get_pdf_status_icon(
                                status.value
                            )
                            lock_icon = "🔒" if node.is_locked else ""
                            version_tag = (
                                f"[v{node.version}]" if node.version else "[v1]"
                            )

                            display_name = (
                                f"{icon} {node.name} {lock_icon} {status_icon}".strip()
                            )
                            item.setText(0, display_name)
                            item.setData(0, Qt.UserRole + 1, version_tag)
                            if message:
                                item.setToolTip(0, message)
        except Exception as e:
            logger.debug(f"Update tree annotation icon failed: {e}")
