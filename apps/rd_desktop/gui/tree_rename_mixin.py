"""Mixin для переименования узлов и файлов в дереве проектов"""
from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox

from apps.rd_desktop.gui.r2_operation_worker import (
    R2Operation,
    R2OperationType,
    R2OperationWorker,
)
from apps.rd_desktop.gui.tree_constants import NODE_ICONS
from apps.rd_desktop.tree_client import NodeType, TreeNode

logger = logging.getLogger(__name__)


class TreeRenameMixin:
    """Mixin для переименования узлов и файлов в R2"""

    def _close_if_open(self, r2_key: str):
        """Закрыть файл в редакторе если он открыт (по r2_key)"""
        if not r2_key:
            return

        from apps.rd_desktop.gui.folder_settings_dialog import get_projects_dir

        projects_dir = get_projects_dir()
        if not projects_dir:
            return

        # Формируем локальный путь из r2_key
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/"):]
        else:
            rel_path = r2_key

        cache_path = Path(projects_dir) / "cache" / rel_path

        # Получаем главное окно
        main_window = self.window()
        if (
            not hasattr(main_window, "_current_pdf_path")
            or not main_window._current_pdf_path
        ):
            return

        # Сравниваем пути
        try:
            current_path = Path(main_window._current_pdf_path).resolve()
            target_path = cache_path.resolve()

            if current_path == target_path:
                # Закрываем файл
                if hasattr(main_window, "_clear_interface"):
                    main_window._clear_interface()
                    logger.info(f"Closed file in editor: {cache_path}")
        except Exception as e:
            logger.error(f"Error checking open file: {e}")

    def _rename_related_files(self, old_r2_key: str, new_r2_key: str, node_id: str):
        """Переименовать связанные файлы (annotation.json, ocr.html, result.json)

        ВАЖНО: Переименовывает файлы в локальном кэше НЕЗАВИСИМО от наличия в R2,
        чтобы избежать потери аннотаций при работе в офлайн режиме.

        R2 операции выполняются асинхронно в фоне.
        """
        old_stem = PurePosixPath(old_r2_key).stem
        new_stem = PurePosixPath(new_r2_key).stem
        r2_prefix = str(PurePosixPath(old_r2_key).parent)

        # Список связанных файлов для переименования
        related_files = [
            (
                f"{r2_prefix}/{old_stem}_annotation.json",
                f"{r2_prefix}/{new_stem}_annotation.json",
            ),
            (f"{r2_prefix}/{old_stem}_ocr.html", f"{r2_prefix}/{new_stem}_ocr.html"),
            (
                f"{r2_prefix}/{old_stem}_result.json",
                f"{r2_prefix}/{new_stem}_result.json",
            ),
            (
                f"{r2_prefix}/{old_stem}_document.md",
                f"{r2_prefix}/{new_stem}_document.md",
            ),
        ]

        # 1. СИНХРОННО: Переименовываем в локальном кэше (мгновенно)
        for old_key, new_key in related_files:
            self._rename_cache_file(old_key, new_key)
            # Обновляем запись в node_files (быстрая DB операция)
            self._update_node_file_r2_key(node_id, old_key, new_key)

        # 2. АСИНХРОННО: Переименовываем в R2 в фоне
        self._start_async_r2_renames(related_files)

    def _start_async_r2_renames(self, related_files: list):
        """Запустить асинхронное переименование файлов в R2"""
        # Создаём worker для переименования
        self._rename_worker = R2OperationWorker()

        for old_key, new_key in related_files:
            self._rename_worker.add_operation(R2Operation(
                operation_type=R2OperationType.RENAME,
                remote_key=old_key,
                new_key=new_key,
                callback_data={"old_key": old_key, "new_key": new_key}
            ))

        self._rename_worker.signals.operation_completed.connect(
            self._on_rename_r2_completed
        )
        self._rename_worker.finished.connect(self._on_all_renames_finished)
        self._rename_worker.start()

    def _on_rename_r2_completed(self, op, success: bool, result, error: str):
        """Callback после переименования файла в R2"""
        if success:
            logger.info(f"Renamed in R2: {op.remote_key} → {op.new_key}")
        else:
            # Не критично - локальный кэш уже переименован
            logger.debug(f"R2 rename skipped (file may not exist): {op.remote_key}")

    def _on_all_renames_finished(self):
        """Все R2 переименования завершены"""
        self._rename_worker = None

    def _start_async_main_file_rename(self, old_r2_key: str, new_r2_key: str):
        """Запустить асинхронное переименование основного PDF файла в R2"""
        self._main_rename_worker = R2OperationWorker()
        self._main_rename_worker.add_operation(R2Operation(
            operation_type=R2OperationType.RENAME,
            remote_key=old_r2_key,
            new_key=new_r2_key,
            callback_data={"old_key": old_r2_key, "new_key": new_r2_key}
        ))
        self._main_rename_worker.signals.operation_completed.connect(
            self._on_main_file_rename_completed
        )
        self._main_rename_worker.start()

    def _on_main_file_rename_completed(self, op, success: bool, result, error: str):
        """Callback после переименования основного PDF в R2"""
        if success:
            logger.info(f"Main PDF renamed in R2: {op.remote_key} → {op.new_key}")
        else:
            logger.warning(f"Main PDF R2 rename failed (may not exist): {op.remote_key} - {error}")
        self._main_rename_worker = None

    def _update_node_file_r2_key(self, node_id: str, old_r2_key: str, new_r2_key: str):
        """Обновить r2_key в таблице node_files"""
        try:
            node_file = self.client.get_node_file_by_r2_key(node_id, old_r2_key)
            if node_file:
                # Обновляем r2_key и file_name
                new_file_name = Path(new_r2_key).name
                self.client.update_node_file(
                    node_file.id, r2_key=new_r2_key, file_name=new_file_name
                )
                logger.info(f"Updated node_file: {old_r2_key} → {new_r2_key}")
        except Exception as e:
            logger.error(f"Failed to update node_file: {e}")

    def _rename_node(self, node: TreeNode):
        """Переименовать узел (для документов также переименовывает в R2)"""
        # Проверка блокировки документа
        if self._check_document_locked(node):
            return

        self._pause_timers()
        try:
            new_name, ok = QInputDialog.getText(
                self, "Переименовать", "Новое название:", text=node.name
            )
            if ok and new_name.strip() and new_name.strip() != node.name:
                try:
                    new_name_clean = new_name.strip()

                    # Проверка уникальности имени в папке
                    if node.parent_id and not self._check_name_unique(
                        node.parent_id, new_name_clean, node.id
                    ):
                        QMessageBox.warning(
                            self,
                            "Ошибка",
                            f"Элемент с именем '{new_name_clean}' уже существует в этой папке",
                        )
                        return

                    # Для документов проверяем и добавляем расширение .pdf
                    if node.node_type == NodeType.DOCUMENT:
                        # Проверяем что имя заканчивается на .pdf (регистронезависимо)
                        if not new_name_clean.lower().endswith(".pdf"):
                            # Автоматически добавляем расширение .pdf
                            new_name_clean = f"{new_name_clean}.pdf"
                            logger.info(
                                f"Added .pdf extension to document name: {new_name_clean}"
                            )
                            # Повторная проверка уникальности после добавления расширения
                            if node.parent_id and not self._check_name_unique(
                                node.parent_id, new_name_clean, node.id
                            ):
                                QMessageBox.warning(
                                    self,
                                    "Ошибка",
                                    f"Элемент с именем '{new_name_clean}' уже существует в этой папке",
                                )
                                return

                    # Для документов переименовываем файл в R2 (асинхронно)
                    if node.node_type == NodeType.DOCUMENT:
                        old_r2_key = node.attributes.get("r2_key", "")

                        # Закрываем файл если он открыт в редакторе
                        self._close_if_open(old_r2_key)

                        if old_r2_key:
                            # Формируем новый ключ (меняем только имя файла)
                            old_path = PurePosixPath(old_r2_key)
                            new_r2_key = str(old_path.parent / new_name_clean)

                            # 1. СИНХРОННО: Обновляем локальный кэш и метаданные (мгновенно)
                            self._rename_cache_file(old_r2_key, new_r2_key)
                            self._update_node_file_r2_key(node.id, old_r2_key, new_r2_key)

                            # Переименовываем связанные файлы (локально + async R2)
                            self._rename_related_files(old_r2_key, new_r2_key, node.id)

                            # Обновляем метаданные в БД
                            node.attributes["r2_key"] = new_r2_key
                            node.attributes["original_name"] = new_name_clean
                            self.client.update_node(
                                node.id,
                                name=new_name_clean,
                                attributes=node.attributes,
                            )

                            # 2. АСИНХРОННО: Переименовываем основной PDF в R2
                            self._start_async_main_file_rename(old_r2_key, new_r2_key)
                        else:
                            self.client.update_node(node.id, name=new_name_clean)
                    else:
                        self.client.update_node(node.id, name=new_name_clean)

                    # Обновляем UI
                    node.name = new_name_clean
                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(100, self._refresh_tree)
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", str(e))
        finally:
            self._resume_timers()
