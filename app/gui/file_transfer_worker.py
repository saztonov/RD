"""
Асинхронные операции загрузки/скачивания файлов
"""

import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class TransferType(Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"


@dataclass
class TransferTask:
    """Задача на передачу файла"""
    transfer_type: TransferType
    local_path: str
    r2_key: str
    node_id: str = ""
    file_size: int = 0
    filename: str = ""
    parent_node_id: str = ""  # Для upload - ID родительской папки


class FileTransferWorker(QThread):
    """Worker для асинхронной загрузки/скачивания файлов"""
    
    # Сигналы
    progress = Signal(str, int, int)  # message, current, total
    finished_task = Signal(TransferTask, bool, str)  # task, success, error_message
    all_finished = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[TransferTask] = []
        self._running = True
    
    def add_task(self, task: TransferTask):
        """Добавить задачу в очередь"""
        self._tasks.append(task)
    
    def run(self):
        """Выполнить все задачи"""
        from rd_core.r2_storage import R2Storage
        
        try:
            r2 = R2Storage()
        except Exception as e:
            for task in self._tasks:
                self.finished_task.emit(task, False, f"R2 ошибка: {e}")
            self.all_finished.emit()
            return
        
        total = len(self._tasks)
        for idx, task in enumerate(self._tasks):
            if not self._running:
                break
            
            try:
                if task.transfer_type == TransferType.UPLOAD:
                    self.progress.emit(f"Загрузка: {task.filename}", idx + 1, total)
                    success = r2.upload_file(task.local_path, task.r2_key)
                    error = "" if success else "Ошибка загрузки в R2"
                else:  # DOWNLOAD
                    self.progress.emit(f"Скачивание: {Path(task.r2_key).name}", idx + 1, total)
                    success = r2.download_file(task.r2_key, task.local_path)
                    error = "" if success else "Ошибка скачивания из R2"
                
                self.finished_task.emit(task, success, error)
                
            except Exception as e:
                logger.exception(f"Transfer error: {e}")
                self.finished_task.emit(task, False, str(e))
        
        self.all_finished.emit()
    
    def stop(self):
        """Остановить обработку"""
        self._running = False

