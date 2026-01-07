"""Менеджер сверки файлов R2/Supabase для дерева проектов"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Set

from PySide6.QtCore import QObject, QThread, Signal

if TYPE_CHECKING:
    from app.tree_client import TreeClient

logger = logging.getLogger(__name__)


class ReconciliationStatus(str, Enum):
    """Статус сверки документа"""
    UNKNOWN = "unknown"     # Не проверялось
    SYNCED = "synced"       # Все файлы в R2 соответствуют записям в Supabase
    NOT_SYNCED = "not_synced"  # Есть расхождения


@dataclass
class DocumentReconciliation:
    """Результат сверки для документа"""
    node_id: str
    status: ReconciliationStatus
    r2_count: int = 0       # Количество файлов в R2
    db_count: int = 0       # Количество записей в Supabase
    orphan_r2: int = 0      # Файлы в R2 без записи в БД
    orphan_db: int = 0      # Записи в БД без файла в R2


class ReconciliationWorker(QThread):
    """Фоновый поток для массовой сверки"""

    progress = Signal(int, int)  # current, total
    document_checked = Signal(str, str)  # node_id, status ("synced" / "not_synced")
    finished_signal = Signal()
    error = Signal(str)

    def __init__(self, documents: List[dict], client: "TreeClient", parent=None):
        """
        Args:
            documents: Список словарей с node_id и r2_key
            client: TreeClient для запросов к Supabase
        """
        super().__init__(parent)
        self.documents = documents
        self.client = client
        self._cancelled = False

    def cancel(self):
        """Отменить сверку"""
        self._cancelled = True

    def run(self):
        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()

            total = len(self.documents)
            for i, doc in enumerate(self.documents):
                if self._cancelled:
                    break

                node_id = doc["node_id"]
                r2_key = doc.get("r2_key", "")

                try:
                    status = self._check_document(r2, node_id, r2_key)
                    self.document_checked.emit(node_id, status)
                except Exception as e:
                    logger.warning(f"Failed to check document {node_id}: {e}")
                    self.document_checked.emit(node_id, ReconciliationStatus.UNKNOWN.value)

                self.progress.emit(i + 1, total)

            self.finished_signal.emit()

        except Exception as e:
            logger.exception(f"Reconciliation worker error: {e}")
            self.error.emit(str(e))

    def _check_document(self, r2, node_id: str, r2_key: str) -> str:
        """Проверить один документ"""
        # Определяем основной префикс по node_id
        main_prefix = f"tree_docs/{node_id}/"

        # Получаем записи из Supabase
        db_files = self.client.get_node_files(node_id)
        db_keys: Set[str] = set()
        for f in db_files:
            # Пропускаем crops_folder - это виртуальная запись
            file_type = f.file_type.value if hasattr(f.file_type, 'value') else str(f.file_type)
            if file_type == "crops_folder":
                continue
            db_keys.add(f.r2_key)

        # Получаем файлы из R2
        r2_files = r2.list_by_prefix(main_prefix)
        r2_keys: Set[str] = set(r2_files)

        # Также проверяем файлы по r2_key из записей БД (могут быть в другом месте)
        for db_key in list(db_keys):
            if not db_key.startswith(main_prefix):
                # Файл в другой папке - проверяем его существование
                if r2.exists(db_key, use_cache=True):
                    r2_keys.add(db_key)

        # Сравниваем только файлы в main_prefix
        main_r2_keys = {k for k in r2_keys if k.startswith(main_prefix)}
        main_db_keys = {k for k in db_keys if k.startswith(main_prefix)}

        # Также учитываем файлы из других мест если они зарегистрированы
        other_db_keys = db_keys - main_db_keys
        other_r2_exists = all(k in r2_keys for k in other_db_keys)

        # Документ синхронизирован если:
        # 1. Все файлы в main_prefix зарегистрированы в БД
        # 2. Все записи БД для main_prefix имеют файлы в R2
        # 3. Все записи из других мест существуют в R2
        orphan_r2 = main_r2_keys - main_db_keys  # Файлы без записей
        orphan_db = main_db_keys - main_r2_keys  # Записи без файлов

        if not orphan_r2 and not orphan_db and other_r2_exists:
            return ReconciliationStatus.SYNCED.value
        else:
            return ReconciliationStatus.NOT_SYNCED.value


class ReconciliationManager(QObject):
    """
    Менеджер сверки R2/Supabase для дерева проектов.

    Хранит статусы сверки и управляет процессом проверки.
    """

    # Сигналы для обновления UI
    status_changed = Signal(str, str)  # node_id, status
    reconciliation_started = Signal()
    reconciliation_finished = Signal()
    reconciliation_progress = Signal(int, int)  # current, total

    def __init__(self, client: "TreeClient", parent=None):
        super().__init__(parent)
        self.client = client
        self._statuses: Dict[str, ReconciliationStatus] = {}
        self._show_status = False  # Отображать ли статус в дереве
        self._worker: Optional[ReconciliationWorker] = None

    @property
    def is_visible(self) -> bool:
        """Отображаются ли статусы сверки"""
        return self._show_status

    def set_visible(self, visible: bool):
        """Установить видимость статусов"""
        self._show_status = visible

    def get_status(self, node_id: str) -> Optional[ReconciliationStatus]:
        """Получить статус сверки для документа"""
        if not self._show_status:
            return None
        return self._statuses.get(node_id)

    def get_status_icon(self, node_id: str) -> str:
        """Получить иконку статуса для отображения в дереве"""
        if not self._show_status:
            return ""

        status = self._statuses.get(node_id)
        if status == ReconciliationStatus.SYNCED:
            return "✓"
        elif status == ReconciliationStatus.NOT_SYNCED:
            return "✗"
        return ""

    def clear_statuses(self):
        """Очистить все статусы"""
        self._statuses.clear()
        self._show_status = False

    def start_reconciliation(self, documents: List[dict]):
        """
        Запустить массовую сверку документов.

        Args:
            documents: Список словарей с node_id и r2_key
        """
        if self._worker and self._worker.isRunning():
            logger.warning("Reconciliation already in progress")
            return

        self._show_status = True
        self.reconciliation_started.emit()

        self._worker = ReconciliationWorker(documents, self.client, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.document_checked.connect(self._on_document_checked)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def cancel_reconciliation(self):
        """Отменить текущую сверку"""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()

    def _on_progress(self, current: int, total: int):
        """Обработать прогресс"""
        self.reconciliation_progress.emit(current, total)

    def _on_document_checked(self, node_id: str, status: str):
        """Обработать результат проверки документа"""
        self._statuses[node_id] = ReconciliationStatus(status)
        self.status_changed.emit(node_id, status)

    def _on_finished(self):
        """Обработать завершение сверки"""
        self.reconciliation_finished.emit()
        self._worker = None

    def _on_error(self, error: str):
        """Обработать ошибку"""
        logger.error(f"Reconciliation error: {error}")
        self.reconciliation_finished.emit()
        self._worker = None


# Глобальный экземпляр менеджера
_reconciliation_manager: Optional[ReconciliationManager] = None


def get_reconciliation_manager(client: "TreeClient" = None) -> ReconciliationManager:
    """Получить или создать глобальный менеджер сверки"""
    global _reconciliation_manager
    if _reconciliation_manager is None:
        if client is None:
            raise ValueError("Client required for first initialization")
        _reconciliation_manager = ReconciliationManager(client)
    return _reconciliation_manager


def reset_reconciliation_manager():
    """Сбросить глобальный менеджер (для тестов)"""
    global _reconciliation_manager
    if _reconciliation_manager:
        _reconciliation_manager.cancel_reconciliation()
        _reconciliation_manager = None
