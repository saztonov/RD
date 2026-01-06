"""Кеш аннотаций с асинхронной синхронизацией в R2"""
import copy
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from rd_core.annotation_io import AnnotationIO
from rd_core.models import Document

logger = logging.getLogger(__name__)


class AnnotationCache(QObject):
    """Кеш аннотаций с отложенной синхронизацией"""
    
    # Сигналы
    synced = Signal(str)  # Когда аннотация синхронизирована с R2
    sync_failed = Signal(str, str)  # node_id, error
    
    def __init__(self):
        super().__init__()
        self._cache: Dict[str, Document] = {}  # node_id -> Document
        self._dirty: Dict[str, float] = {}  # node_id -> last_modified_time
        self._metadata: Dict[str, dict] = {}  # node_id -> {pdf_path, r2_key, ann_path}
        
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(False)
        self._sync_timer.timeout.connect(self._check_sync)
        self._sync_timer.start(1000)  # Проверка каждую секунду
        
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ann_sync")
        self._sync_delay = 3.0  # Синхронизация через 3 секунды после последнего изменения
        self._local_save_delay = 0.5  # Локальное сохранение через 0.5 секунды
        
        self._local_save_timers: Dict[str, QTimer] = {}
    
    def set(self, node_id: str, document: Document, pdf_path: str, r2_key: str = "", 
            ann_path: str = ""):
        """Сохранить аннотацию в кеш"""
        self._cache[node_id] = document
        self._metadata[node_id] = {
            "pdf_path": pdf_path,
            "r2_key": r2_key,
            "ann_path": ann_path or self._get_annotation_path(pdf_path)
        }
    
    def get(self, node_id: str) -> Optional[Document]:
        """Получить аннотацию из кеша"""
        return self._cache.get(node_id)
    
    def mark_dirty(self, node_id: str):
        """Пометить аннотацию как измененную"""
        if node_id not in self._cache:
            return
        
        self._dirty[node_id] = time.time()
        
        # Запланировать локальное сохранение
        if node_id not in self._local_save_timers:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda nid=node_id: self._save_local(nid))
            self._local_save_timers[node_id] = timer
        
        timer = self._local_save_timers[node_id]
        if timer.isActive():
            timer.stop()
        timer.start(int(self._local_save_delay * 1000))
    
    def _save_local(self, node_id: str):
        """Сохранить локально (быстро, не блокирует)"""
        if node_id not in self._cache:
            return
        
        document = self._cache[node_id]
        metadata = self._metadata.get(node_id, {})
        ann_path = metadata.get("ann_path")
        
        if not ann_path:
            return
        
        try:
            # Копируем для фонового сохранения
            doc_copy = copy.deepcopy(document)
            self._executor.submit(self._background_save_local, ann_path, doc_copy)
        except Exception as e:
            logger.error(f"Local save failed for {node_id}: {e}")
    
    def _background_save_local(self, ann_path: str, doc: Document):
        """Фоновое локальное сохранение"""
        try:
            AnnotationIO.save_annotation(doc, ann_path)
            logger.debug(f"Annotation cached locally: {ann_path}")
        except Exception as e:
            logger.error(f"Background local save failed: {e}")
    
    def _check_sync(self):
        """Проверить, какие аннотации нужно синхронизировать с R2"""
        current_time = time.time()
        to_sync = []
        
        for node_id, modified_time in list(self._dirty.items()):
            if current_time - modified_time >= self._sync_delay:
                to_sync.append(node_id)
        
        for node_id in to_sync:
            self._sync_to_r2(node_id)
    
    def _sync_to_r2(self, node_id: str):
        """Синхронизировать с R2 (асинхронно)"""
        if node_id not in self._cache:
            return

        del self._dirty[node_id]

        document = self._cache[node_id]
        metadata = self._metadata.get(node_id, {})

        r2_key = metadata.get("r2_key")
        ann_path = metadata.get("ann_path")

        if not r2_key or not ann_path:
            return

        # Проверяем офлайн статус - если офлайн, сразу добавляем в очередь
        if self._is_offline():
            ann_r2_key = self._get_annotation_r2_key(r2_key)
            self._add_to_sync_queue(node_id, ann_path, ann_r2_key)
            logger.debug(f"Офлайн: добавлена в очередь синхронизация {node_id}")
            return

        # Копируем для фонового потока
        doc_copy = copy.deepcopy(document)
        self._executor.submit(
            self._background_sync_r2,
            node_id, ann_path, doc_copy, r2_key
        )

    def _is_offline(self) -> bool:
        """Проверить, работаем ли мы в офлайн режиме"""
        try:
            # Импортируем здесь чтобы избежать циклических импортов
            from app.gui.main_window import MainWindow
            from PySide6.QtWidgets import QApplication
            from app.gui.connection_manager import ConnectionStatus

            app = QApplication.instance()
            if app:
                for widget in app.topLevelWidgets():
                    if isinstance(widget, MainWindow):
                        if hasattr(widget, 'connection_manager'):
                            status = widget.connection_manager.get_status()
                            return status != ConnectionStatus.CONNECTED
            return False
        except Exception:
            return False
    
    def _background_sync_r2(self, node_id: str, ann_path: str, doc: Document,
                           r2_key: str):
        """Фоновая синхронизация с R2"""
        try:
            # Сначала сохраняем локально (если еще не сохранено)
            AnnotationIO.save_annotation(doc, ann_path)

            # Загружаем в R2
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
            ann_r2_key = self._get_annotation_r2_key(r2_key)

            if r2.upload_file(ann_path, ann_r2_key):
                logger.info(f"Annotation synced to R2: {ann_r2_key}")
                self.synced.emit(node_id)

                # Регистрируем файл в БД
                self._register_node_file(node_id, ann_r2_key, ann_path)
            else:
                # Ошибка загрузки - добавляем в очередь отложенной синхронизации
                self._add_to_sync_queue(node_id, ann_path, ann_r2_key)
                self.sync_failed.emit(node_id, "Не удалось загрузить в R2")

        except Exception as e:
            logger.error(f"R2 sync failed for {node_id}: {e}")
            # Добавляем в очередь для повторной попытки при восстановлении соединения
            ann_r2_key = self._get_annotation_r2_key(r2_key)
            self._add_to_sync_queue(node_id, ann_path, ann_r2_key)
            self.sync_failed.emit(node_id, str(e))

    def _add_to_sync_queue(self, node_id: str, ann_path: str, ann_r2_key: str):
        """Добавить операцию в очередь отложенной синхронизации"""
        try:
            from uuid import uuid4
            from datetime import datetime
            from app.gui.sync_queue import SyncOperation, SyncOperationType, get_sync_queue

            queue = get_sync_queue()

            # Проверяем, нет ли уже такой операции в очереди
            for op in queue.get_pending_operations():
                if op.r2_key == ann_r2_key:
                    logger.debug(f"Операция уже в очереди: {ann_r2_key}")
                    return

            operation = SyncOperation(
                id=str(uuid4()),
                type=SyncOperationType.UPLOAD_FILE,
                timestamp=datetime.now().isoformat(),
                local_path=ann_path,
                r2_key=ann_r2_key,
                node_id=node_id,
                data={"content_type": "application/json", "is_annotation": True}
            )
            queue.add_operation(operation)
            logger.info(f"Добавлена операция в очередь: annotation для {node_id}")

        except Exception as e:
            logger.error(f"Ошибка добавления в очередь: {e}")
    
    def _register_node_file(self, node_id: str, ann_r2_key: str, ann_path: str):
        """Регистрация файла в БД"""
        try:
            from app.tree_client import FileType, TreeClient
            
            client = TreeClient()
            client.upsert_node_file(
                node_id=node_id,
                file_type=FileType.ANNOTATION,
                r2_key=ann_r2_key,
                file_name=Path(ann_path).name,
                file_size=Path(ann_path).stat().st_size,
                mime_type="application/json"
            )
            
            # Обновляем флаг has_annotation
            node = client.get_node(node_id)
            if node and not node.attributes.get("has_annotation"):
                attrs = node.attributes.copy()
                attrs["has_annotation"] = True
                client.update_node(node_id, attributes=attrs)
                
        except Exception as e:
            logger.debug(f"Register node file failed: {e}")
    
    def force_sync(self, node_id: str):
        """Принудительно синхронизировать с R2"""
        if node_id in self._dirty:
            self._sync_to_r2(node_id)
    
    def force_sync_all(self):
        """Синхронизировать все несохраненные изменения"""
        for node_id in list(self._dirty.keys()):
            self._sync_to_r2(node_id)
    
    def clear(self, node_id: str):
        """Очистить кеш для узла"""
        self._cache.pop(node_id, None)
        self._dirty.pop(node_id, None)
        self._metadata.pop(node_id, None)
        if node_id in self._local_save_timers:
            self._local_save_timers[node_id].stop()
            del self._local_save_timers[node_id]
    
    @staticmethod
    def _get_annotation_path(pdf_path: str) -> str:
        """Путь к annotation.json"""
        p = Path(pdf_path)
        return str(p.parent / f"{p.stem}_annotation.json")
    
    @staticmethod
    def _get_annotation_r2_key(pdf_r2_key: str) -> str:
        """R2 ключ для annotation.json"""
        from pathlib import PurePosixPath
        p = PurePosixPath(pdf_r2_key)
        return str(p.parent / f"{p.stem}_annotation.json")


# Глобальный экземпляр
_annotation_cache: Optional[AnnotationCache] = None


def get_annotation_cache() -> AnnotationCache:
    """Получить глобальный кеш аннотаций"""
    global _annotation_cache
    if _annotation_cache is None:
        _annotation_cache = AnnotationCache()
    return _annotation_cache
