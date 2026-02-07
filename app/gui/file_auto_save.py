"""Авто-сохранение аннотаций через кеш"""
import logging
from pathlib import Path

from PySide6.QtCore import QTimer


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
    """Миксин для авто-сохранения аннотаций через кеш"""

    _current_r2_key: str = ""
    _current_node_id: str = ""
    _annotation_synced: bool = False

    def _auto_save_annotation(self):
        """Авто-сохранение разметки через кеш (мгновенно)"""
        if not self.annotation_document or not self._current_pdf_path:
            return
        
        if not self._current_node_id:
            return
        
        from app.gui.annotation_cache import get_annotation_cache
        
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
        """Принудительно синхронизировать с R2"""
        if not self._current_node_id:
            return
        
        from app.gui.annotation_cache import get_annotation_cache
        cache = get_annotation_cache()
        cache.force_sync(self._current_node_id)
    
    def _setup_annotation_cache_signals(self):
        """Подключить сигналы кеша аннотаций"""
        from app.gui.annotation_cache import get_annotation_cache
        
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
            from app.tree_client import TreeClient
            from rd_core.pdf_status import calculate_pdf_status
            from rd_core.r2_storage import R2Storage

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

                            from app.gui.tree_node_operations import NODE_ICONS

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
