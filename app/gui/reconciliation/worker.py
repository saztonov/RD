"""Фоновый worker для сверки файлов."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Set

from PySide6.QtCore import QThread, Signal

from .types import DiscrepancyType, FileDiscrepancy

if TYPE_CHECKING:
    from app.tree_client import TreeClient, TreeNode

logger = logging.getLogger(__name__)


class ReconciliationWorker(QThread):
    """Фоновый поток для сверки файлов"""

    progress = Signal(str)  # Сообщение о прогрессе
    finished_signal = Signal(list)  # Список FileDiscrepancy
    error = Signal(str)

    def __init__(self, node: "TreeNode", client: "TreeClient", parent=None):
        super().__init__(parent)
        self.node = node
        self.client = client

    def run(self):
        try:
            from rd_core.r2_storage import R2Storage

            discrepancies: List[FileDiscrepancy] = []

            # Получаем записи из Supabase СНАЧАЛА
            self.progress.emit("Загрузка записей из Supabase...")
            db_files = self.client.get_node_files(self.node.id)
            db_keys_map: Dict[str, dict] = {}
            for f in db_files:
                db_keys_map[f.r2_key] = {
                    "id": f.id,
                    "file_size": f.file_size,
                    "file_type": f.file_type.value if hasattr(f.file_type, 'value') else str(f.file_type),
                    "file_name": f.file_name,
                }

            self.progress.emit(f"Найдено записей в Supabase: {len(db_files)}")

            # Собираем уникальные префиксы из r2_key записей БД
            prefixes: Set[str] = set()

            # Основной префикс по node_id документа
            main_prefix = f"tree_docs/{self.node.id}/"
            prefixes.add(main_prefix)

            # Добавляем префиксы из существующих записей
            for r2_key in db_keys_map.keys():
                if "/" in r2_key:
                    dir_prefix = "/".join(r2_key.rsplit("/", 1)[:-1]) + "/"
                    prefixes.add(dir_prefix)

            self.progress.emit(f"Сканирование R2 по {len(prefixes)} префикс(ам)...")

            # Получаем список файлов из R2 по всем префиксам
            r2 = R2Storage()
            r2_keys_map: Dict[str, dict] = {}

            for prefix in prefixes:
                r2_files = r2.list_objects_with_metadata(prefix, use_cache=False)
                for f in r2_files:
                    r2_keys_map[f["Key"]] = f

            self.progress.emit(f"Найдено файлов в R2: {len(r2_keys_map)}")

            # Сравниваем
            all_keys: Set[str] = set(r2_keys_map.keys()) | set(db_keys_map.keys())

            for key in all_keys:
                in_r2 = key in r2_keys_map
                in_db = key in db_keys_map

                if in_r2 and not in_db:
                    # Сирота в R2 - только из папки ЭТОГО документа
                    if not key.startswith(main_prefix):
                        continue

                    discrepancies.append(FileDiscrepancy(
                        r2_key=key,
                        discrepancy_type=DiscrepancyType.ORPHAN_R2,
                        r2_size=r2_keys_map[key].get("Size", 0),
                        file_name=key.rsplit("/", 1)[-1] if "/" in key else key,
                    ))
                elif in_db and not in_r2:
                    db_info = db_keys_map[key]
                    file_type = db_info["file_type"]

                    # Специальная обработка для crops_folder
                    if file_type == "crops_folder":
                        folder_prefix = key if key.endswith("/") else key + "/"
                        has_files_in_folder = any(
                            r2_key.startswith(folder_prefix) for r2_key in r2_keys_map.keys()
                        )
                        if has_files_in_folder:
                            continue

                    # Сирота в БД
                    discrepancies.append(FileDiscrepancy(
                        r2_key=key,
                        discrepancy_type=DiscrepancyType.ORPHAN_DB,
                        db_size=db_info["file_size"],
                        db_file_id=db_info["id"],
                        file_type=file_type,
                        file_name=db_info["file_name"],
                    ))
                elif in_r2 and in_db:
                    # Проверяем размер
                    r2_size = r2_keys_map[key].get("Size", 0) or 0
                    db_size = db_keys_map[key]["file_size"] or 0

                    if db_size > 0 and r2_size > 0 and r2_size != db_size:
                        db_info = db_keys_map[key]
                        discrepancies.append(FileDiscrepancy(
                            r2_key=key,
                            discrepancy_type=DiscrepancyType.SIZE_MISMATCH,
                            r2_size=r2_size,
                            db_size=db_size,
                            db_file_id=db_info["id"],
                            file_type=db_info["file_type"],
                            file_name=db_info["file_name"],
                        ))

            self.progress.emit(f"Сверка завершена. Найдено несоответствий: {len(discrepancies)}")
            self.finished_signal.emit(discrepancies)

        except Exception as e:
            logger.exception(f"Reconciliation error: {e}")
            self.error.emit(str(e))
