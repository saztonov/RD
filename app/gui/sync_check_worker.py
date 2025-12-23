"""
Воркер для фоновой проверки синхронизации файлов между локальным кэшем и R2
"""

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class SyncStatus(str, Enum):
    """Статус синхронизации"""
    SYNCED = "synced"           # Файлы идентичны
    NOT_SYNCED = "not_synced"   # Файлы отличаются
    MISSING_LOCAL = "missing"   # Нет локальных файлов
    CHECKING = "checking"       # Проверка в процессе
    UNKNOWN = "unknown"         # Статус неизвестен


@dataclass
class SyncCheckResult:
    """Результат проверки синхронизации для узла"""
    node_id: str
    status: SyncStatus
    r2_files: int = 0
    local_files: int = 0
    mismatched_files: List[str] = None
    
    def __post_init__(self):
        if self.mismatched_files is None:
            self.mismatched_files = []


def compute_md5(file_path: Path) -> Optional[str]:
    """Вычислить MD5 хеш файла"""
    try:
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5.update(chunk)
        return md5.hexdigest()
    except Exception as e:
        logger.error(f"Failed to compute MD5 for {file_path}: {e}")
        return None


class SyncCheckWorker(QThread):
    """Воркер для проверки синхронизации файлов папки заданий с R2"""
    
    # Сигналы
    result_ready = Signal(str, str)  # node_id, status (SyncStatus value)
    check_finished = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes_to_check: List[Dict] = []  # [{node_id, r2_prefix, local_folder}]
        self._running = True
    
    def add_check(self, node_id: str, r2_prefix: str, local_folder: str):
        """Добавить узел для проверки"""
        self._nodes_to_check.append({
            "node_id": node_id,
            "r2_prefix": r2_prefix,
            "local_folder": local_folder,
        })
    
    def stop(self):
        """Остановить воркер"""
        self._running = False
        self.wait()
    
    def run(self):
        """Выполнить проверку всех узлов"""
        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
        except Exception as e:
            logger.error(f"Failed to init R2Storage for sync check: {e}")
            self.check_finished.emit()
            return
        
        for check_info in self._nodes_to_check:
            if not self._running:
                break
            
            node_id = check_info["node_id"]
            r2_prefix = check_info["r2_prefix"]
            local_folder = Path(check_info["local_folder"])
            
            try:
                status = self._check_node_sync(r2, r2_prefix, local_folder)
                self.result_ready.emit(node_id, status.value)
            except Exception as e:
                logger.error(f"Sync check failed for {node_id}: {e}")
                self.result_ready.emit(node_id, SyncStatus.UNKNOWN.value)
        
        self.check_finished.emit()
    
    def _check_node_sync(self, r2, r2_prefix: str, local_folder: Path) -> SyncStatus:
        """Проверить синхронизацию для одного узла"""
        # Получаем файлы из R2 (приоритет R2)
        r2_files = r2.list_objects_with_metadata(r2_prefix)
        
        if not r2_files:
            # Нет файлов на R2 - считаем синхронизированным
            return SyncStatus.SYNCED
        
        # Проверяем каждый файл из R2
        for r2_file in r2_files:
            r2_key = r2_file["Key"]
            r2_size = r2_file.get("Size", 0)
            r2_etag = r2_file.get("ETag", "")
            
            # Формируем локальный путь
            if r2_key.startswith("tree_docs/"):
                rel_path = r2_key[len("tree_docs/"):]
            else:
                rel_path = r2_key.replace(r2_prefix, "").lstrip("/")
            
            # Для TASK_FOLDER r2_prefix = "tree_docs/{node_id}/"
            # Локальный файл будет в local_folder / filename
            local_file = local_folder / Path(rel_path).name
            
            # Альтернативный путь с полной структурой
            if not local_file.exists():
                local_file = local_folder / rel_path
            
            # Если локальный файл не существует - не синхронизировано
            if not local_file.exists():
                return SyncStatus.NOT_SYNCED
            
            # Сравниваем размер
            local_size = local_file.stat().st_size
            if local_size != r2_size:
                return SyncStatus.NOT_SYNCED
            
            # Если есть ETag и он выглядит как MD5 (32 символа) - сравниваем хеши
            if r2_etag and len(r2_etag) == 32 and "-" not in r2_etag:
                local_md5 = compute_md5(local_file)
                if local_md5 and local_md5 != r2_etag:
                    return SyncStatus.NOT_SYNCED
        
        return SyncStatus.SYNCED

