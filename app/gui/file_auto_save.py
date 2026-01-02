"""Авто-сохранение аннотаций"""
import copy
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QTimer

from rd_core.annotation_io import AnnotationIO
from rd_core.models import Document

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)


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
    """Миксин для авто-сохранения аннотаций"""
    
    _current_r2_key: str = ""
    _current_node_id: str = ""
    _auto_save_timer: QTimer = None
    _pending_save: bool = False
    _annotation_synced: bool = False
    
    def _auto_save_annotation(self):
        """Авто-сохранение разметки при изменении блоков"""
        if not self.annotation_document or not self._current_pdf_path:
            return
        
        self._pending_save = True
        
        if self._auto_save_timer is None:
            self._auto_save_timer = QTimer(self)
            self._auto_save_timer.setSingleShot(True)
            self._auto_save_timer.timeout.connect(self._do_auto_save)
        
        # Если аннотация ещё не синхронизирована - сохранить сразу (через 100мс для debounce)
        # Иначе - через 5 секунд для накопления изменений
        if not self._annotation_synced:
            delay = 100  # Первое сохранение - почти сразу
        else:
            delay = 5000  # Последующие - через 5 секунд
        
        # Перезапускаем таймер (debounce)
        if self._auto_save_timer.isActive():
            self._auto_save_timer.stop()
        self._auto_save_timer.start(delay)
    
    def _do_auto_save(self):
        """Выполнить отложенное сохранение в фоновом потоке"""
        if not self._pending_save:
            return
        if not self.annotation_document or not self._current_pdf_path:
            return
        
        self._pending_save = False
        
        # Копируем данные для фонового потока
        ann_path = str(get_annotation_path(self._current_pdf_path))
        doc_copy = copy.deepcopy(self.annotation_document)
        r2_key = self._current_r2_key if hasattr(self, '_current_r2_key') else ""
        node_id = self._current_node_id if hasattr(self, '_current_node_id') else ""
        
        # Сохраняем в фоновом потоке
        _executor.submit(self._background_save, ann_path, doc_copy, r2_key, node_id)
    
    def _background_save(self, ann_path: str, doc: Document, r2_key: str, node_id: str):
        """Фоновое сохранение (не блокирует UI)"""
        try:
            AnnotationIO.save_annotation(doc, ann_path)
            logger.debug(f"Annotation auto-saved: {ann_path}")
            
            if r2_key:
                self._background_sync_r2(ann_path, r2_key, node_id)
        except Exception as e:
            logger.error(f"Auto-save annotation failed: {e}")
    
    def _background_sync_r2(self, ann_path: str, r2_key: str, node_id: str):
        """Фоновая синхронизация с R2"""
        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)
            r2.upload_file(ann_path, ann_r2_key)
            logger.debug(f"Annotation synced to R2: {ann_r2_key}")
            
            # Помечаем что аннотация синхронизирована
            self._annotation_synced = True
            
            # Записываем файл в БД node_files и обновляем флаг has_annotation
            if node_id:
                self._register_node_file(
                    node_id, "annotation", ann_r2_key, 
                    Path(ann_path).name, Path(ann_path).stat().st_size
                )
                # Обновляем флаг has_annotation в узле
                try:
                    from app.tree_client import TreeClient
                    client = TreeClient()
                    node = client.get_node(node_id)
                    if node and not node.attributes.get("has_annotation"):
                        attrs = node.attributes.copy()
                        attrs["has_annotation"] = True
                        client.update_node(node_id, attributes=attrs)
                        # Обновляем UI в главном потоке (lambda с default для захвата значения)
                        QTimer.singleShot(0, lambda nid=node_id: self._update_tree_annotation_icon(nid))
                except Exception as e2:
                    logger.debug(f"Update has_annotation in background failed: {e2}")
        except Exception as e:
            logger.error(f"Sync annotation to R2 failed: {e}")
    
    def _flush_pending_save(self):
        """Принудительно сохранить несохранённые изменения"""
        if self._auto_save_timer and self._auto_save_timer.isActive():
            self._auto_save_timer.stop()
        if self._pending_save:
            self._do_auto_save()
    
    def _register_node_file(
        self, node_id: str, file_type: str, r2_key: str, 
        file_name: str, file_size: int = 0, mime_type: str = None
    ):
        """Регистрация файла в таблице node_files"""
        try:
            from app.tree_client import TreeClient, FileType
            client = TreeClient()
            
            ft = FileType(file_type) if file_type in [e.value for e in FileType] else FileType.PDF
            mt = mime_type or self._guess_mime_type(file_name)
            
            client.upsert_node_file(
                node_id=node_id,
                file_type=ft,
                r2_key=r2_key,
                file_name=file_name,
                file_size=file_size,
                mime_type=mt,
            )
            logger.debug(f"Registered node file: {file_type} -> {r2_key}")
        except Exception as e:
            logger.error(f"Failed to register node file: {e}")
    
    def _guess_mime_type(self, filename: str) -> str:
        """Определить MIME тип по расширению"""
        ext = Path(filename).suffix.lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".json": "application/json",
            ".md": "text/markdown",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".zip": "application/zip",
        }
        return mime_map.get(ext, "application/octet-stream")
    
    def _update_tree_annotation_icon(self, node_id: str):
        """Обновить иконку аннотации в дереве (вызывается из главного потока)"""
        if not hasattr(self, 'project_tree') or not self.project_tree:
            return
        
        try:
            from PySide6.QtCore import Qt, QTimer
            from app.tree_client import TreeClient
            from rd_core.pdf_status import calculate_pdf_status
            from rd_core.r2_storage import R2Storage
            
            item = self.project_tree._node_map.get(node_id)
            if item:
                node = item.data(0, Qt.UserRole)
                if node and hasattr(node, 'attributes'):
                    node.attributes["has_annotation"] = True
                    item.setData(0, Qt.UserRole, node)
                    
                    # Обновляем статус PDF в БД
                    r2_key = node.attributes.get("r2_key", "")
                    if r2_key:
                        client = TreeClient()
                        r2 = R2Storage()
                        status, message = calculate_pdf_status(r2, node_id, r2_key)
                        client.update_pdf_status(node_id, status.value, message)
                        
                        # Обновляем дерево
                        QTimer.singleShot(100, self.project_tree._refresh_tree)
        except Exception as e:
            logger.debug(f"Update tree annotation icon failed: {e}")



