"""
Асинхронный worker для R2 операций (текст, exists, rename, delete)
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


class R2OperationType(Enum):
    """Типы R2 операций"""
    DOWNLOAD_FILE = "download_file"
    DOWNLOAD_TEXT = "download_text"
    UPLOAD_FILE = "upload_file"
    UPLOAD_TEXT = "upload_text"
    EXISTS = "exists"
    RENAME = "rename"
    DELETE = "delete"


@dataclass
class R2Operation:
    """Операция R2"""
    operation_type: R2OperationType
    remote_key: str
    local_path: Optional[str] = None
    content: Optional[str] = None  # Для text операций
    new_key: Optional[str] = None  # Для rename
    content_type: Optional[str] = None  # Для upload
    callback_data: Any = field(default_factory=dict)  # Данные для callback


class R2OperationSignals(QObject):
    """Сигналы для R2 операций"""
    # operation, success, result (текст/bool/None), error_message
    operation_completed = Signal(object, bool, object, str)
    progress = Signal(str, int, int)  # message, current, total


class R2OperationWorker(QThread):
    """Worker для асинхронных R2 операций"""

    def __init__(self, parent=None, max_workers: int = 4):
        super().__init__(parent)
        self.signals = R2OperationSignals()
        self._operations: list[R2Operation] = []
        self._running = True
        self.max_workers = max_workers
        self._completed = 0
        self._lock = threading.Lock()
        self._r2 = None

    def add_operation(self, operation: R2Operation):
        """Добавить операцию в очередь"""
        with self._lock:
            self._operations.append(operation)

    def add_operations(self, operations: list[R2Operation]):
        """Добавить несколько операций"""
        with self._lock:
            self._operations.extend(operations)

    def _get_r2(self):
        """Получить R2 storage (ленивая инициализация)"""
        if self._r2 is None:
            from rd_adapters.storage import R2SyncStorage
            self._r2 = R2SyncStorage()
        return self._r2

    def _process_operation(self, op: R2Operation) -> tuple[bool, Any, str]:
        """Обработать одну операцию"""
        if not self._running:
            return False, None, "Отменено"

        try:
            r2 = self._get_r2()

            if op.operation_type == R2OperationType.DOWNLOAD_FILE:
                success = r2.download_file(op.remote_key, op.local_path)
                return success, None, "" if success else "Ошибка скачивания"

            elif op.operation_type == R2OperationType.DOWNLOAD_TEXT:
                result = r2.download_text(op.remote_key)
                return result is not None, result, "" if result else "Файл не найден"

            elif op.operation_type == R2OperationType.UPLOAD_FILE:
                success = r2.upload_file(op.local_path, op.remote_key, op.content_type)
                return success, None, "" if success else "Ошибка загрузки"

            elif op.operation_type == R2OperationType.UPLOAD_TEXT:
                success = r2.upload_text(op.content, op.remote_key, op.content_type)
                return success, None, "" if success else "Ошибка загрузки текста"

            elif op.operation_type == R2OperationType.EXISTS:
                exists = r2.exists(op.remote_key)
                return True, exists, ""

            elif op.operation_type == R2OperationType.RENAME:
                # R2 не поддерживает rename напрямую - копируем и удаляем
                if hasattr(r2, 'rename_object'):
                    success = r2.rename_object(op.remote_key, op.new_key)
                else:
                    # Fallback: copy + delete
                    content = r2.download_text(op.remote_key)
                    if content is None:
                        # Попробуем как файл
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False) as tmp:
                            tmp_path = tmp.name
                        if r2.download_file(op.remote_key, tmp_path):
                            success = r2.upload_file(tmp_path, op.new_key)
                            if success:
                                r2.delete_object(op.remote_key)
                            import os
                            os.unlink(tmp_path)
                        else:
                            success = False
                    else:
                        success = r2.upload_text(content, op.new_key)
                        if success:
                            r2.delete_object(op.remote_key)
                return success, None, "" if success else "Ошибка переименования"

            elif op.operation_type == R2OperationType.DELETE:
                success = r2.delete_object(op.remote_key)
                return success, None, "" if success else "Ошибка удаления"

            return False, None, f"Неизвестный тип операции: {op.operation_type}"

        except Exception as e:
            logger.exception(f"R2 operation error: {e}")
            return False, None, str(e)

    def _process_with_progress(self, op: R2Operation) -> tuple[R2Operation, bool, Any, str]:
        """Обработать операцию и обновить прогресс"""
        success, result, error = self._process_operation(op)

        with self._lock:
            self._completed += 1
            current = self._completed
            total = len(self._operations)

        # Отправляем прогресс
        action_names = {
            R2OperationType.DOWNLOAD_FILE: "Скачивание",
            R2OperationType.DOWNLOAD_TEXT: "Загрузка",
            R2OperationType.UPLOAD_FILE: "Выгрузка",
            R2OperationType.UPLOAD_TEXT: "Сохранение",
            R2OperationType.EXISTS: "Проверка",
            R2OperationType.RENAME: "Переименование",
            R2OperationType.DELETE: "Удаление",
        }
        action = action_names.get(op.operation_type, "Операция")
        self.signals.progress.emit(f"{action}: {op.remote_key}", current, total)

        return op, success, result, error

    def run(self):
        """Выполнить все операции"""
        self._completed = 0

        if not self._operations:
            return

        # Параллельная обработка
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_with_progress, op): op
                for op in self._operations
            }

            for future in as_completed(futures):
                if not self._running:
                    for f in futures:
                        f.cancel()
                    break

                try:
                    op, success, result, error = future.result()
                    self.signals.operation_completed.emit(op, success, result, error)
                except Exception as e:
                    op = futures[future]
                    logger.exception(f"Operation execution failed: {e}")
                    self.signals.operation_completed.emit(op, False, None, str(e))

        # Очищаем очередь
        with self._lock:
            self._operations.clear()

    def stop(self):
        """Остановить обработку"""
        self._running = False


# Глобальный worker для простых операций
_global_worker: Optional[R2OperationWorker] = None
_worker_lock = threading.Lock()


def get_r2_worker() -> R2OperationWorker:
    """Получить глобальный R2 worker"""
    global _global_worker
    with _worker_lock:
        if _global_worker is None:
            _global_worker = R2OperationWorker()
        return _global_worker


def run_r2_operation(
    operation: R2Operation,
    on_complete: callable = None
) -> R2OperationWorker:
    """Запустить одну R2 операцию асинхронно

    Args:
        operation: Операция для выполнения
        on_complete: Callback (op, success, result, error)

    Returns:
        Worker для отслеживания
    """
    worker = R2OperationWorker()
    worker.add_operation(operation)

    if on_complete:
        worker.signals.operation_completed.connect(on_complete)

    worker.start()
    return worker


def run_r2_operations(
    operations: list[R2Operation],
    on_complete: callable = None,
    on_all_done: callable = None
) -> R2OperationWorker:
    """Запустить несколько R2 операций асинхронно

    Args:
        operations: Список операций
        on_complete: Callback для каждой операции
        on_all_done: Callback когда все завершены

    Returns:
        Worker для отслеживания
    """
    worker = R2OperationWorker()
    worker.add_operations(operations)

    if on_complete:
        worker.signals.operation_completed.connect(on_complete)

    if on_all_done:
        worker.finished.connect(on_all_done)

    worker.start()
    return worker
