"""Диалог для просмотра файлов на R2"""
from __future__ import annotations

import logging
import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from app.gui.r2_viewer.delete_worker import R2DeleteWorker
from app.gui.r2_viewer.download_worker import R2DownloadWorker

logger = logging.getLogger(__name__)


class R2FilesDialog(QDialog):
    """Диалог со списком файлов на R2"""

    files_changed = Signal()

    def __init__(
        self,
        r2_base_url: str,
        r2_files: list,
        parent=None,
        r2_prefix: str = "",
        node_id: Optional[str] = None,
        local_folder: Optional[Path] = None,
        latest_job_id: Optional[str] = None,
    ):
        super().__init__(parent)
        self.r2_base_url = r2_base_url
        self.r2_files = r2_files
        self.r2_prefix = r2_prefix
        self.node_id = node_id
        self.local_folder = local_folder
        self.latest_job_id = latest_job_id  # ID последнего OCR запуска
        self.current_path = []
        self._worker = None
        self.setWindowTitle("Файлы на R2 Storage")
        self.setMinimumSize(600, 500)
        self._setup_ui()

    def _setup_ui(self):
        """Настроить UI"""
        layout = QVBoxLayout(self)

        nav_layout = QHBoxLayout()

        self.back_btn = QPushButton("⬅️ Назад")
        self.back_btn.setMaximumWidth(80)
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        nav_layout.addWidget(self.back_btn)

        self.header = QLabel(f"📦 {self.r2_base_url}")
        self.header.setWordWrap(True)
        self.header.setStyleSheet("font-weight: bold; padding: 5px;")
        nav_layout.addWidget(self.header, 1)

        layout.addLayout(nav_layout)

        self.files_list = QListWidget()
        self.files_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.files_list.setIconSize(self.files_list.iconSize() * 1.5)
        self.files_list.itemDoubleClicked.connect(self._on_file_double_clicked)
        self.files_list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.files_list)

        actions_layout = QHBoxLayout()

        self.download_btn = QPushButton("📥 Скачать")
        self.download_btn.clicked.connect(self._download_selected)
        self.download_btn.setEnabled(False)
        actions_layout.addWidget(self.download_btn)

        self.download_all_btn = QPushButton("📥 Скачать всё")
        self.download_all_btn.clicked.connect(self._download_all)
        actions_layout.addWidget(self.download_all_btn)

        actions_layout.addStretch()

        self.delete_btn = QPushButton("🗑️ Удалить")
        self.delete_btn.clicked.connect(self._delete_selected)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setStyleSheet("color: #d32f2f;")
        actions_layout.addWidget(self.delete_btn)

        layout.addLayout(actions_layout)

        hint = QLabel(
            "💡 Дважды кликните для открытия. Выделите файлы для скачивания/удаления."
        )
        hint.setStyleSheet("color: gray; font-size: 9pt; padding: 5px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_files(self.r2_files)

    def _on_selection_changed(self):
        """Обработчик изменения выделения"""
        selected = self.files_list.selectedItems()
        has_selection = len(selected) > 0
        self.download_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

        if has_selection:
            self.download_btn.setText(f"📥 Скачать ({len(selected)})")
            self.delete_btn.setText(f"🗑️ Удалить ({len(selected)})")
        else:
            self.download_btn.setText("📥 Скачать")
            self.delete_btn.setText("🗑️ Удалить")

    def _is_inside_ocr_runs(self) -> bool:
        """Проверить, находимся ли внутри папки ocr_runs"""
        if not self.current_path:
            return False
        # Проверяем, есть ли в пути папка ocr_runs
        return any(p.get("name") == "ocr_runs" for p in self.current_path)

    def _populate_files(self, files: list):
        """Заполнить список файлов"""
        self.files_list.clear()

        # Проверяем, находимся ли внутри папки ocr_runs
        inside_ocr_runs = self._is_inside_ocr_runs()

        for file_info in files:
            icon = file_info.get("icon", "📄")
            name = file_info.get("name", "")
            size = file_info.get("size", 0)
            is_dir = file_info.get("is_dir", False)

            # Проверяем, является ли это последней распознанной папкой
            is_latest = (
                inside_ocr_runs
                and is_dir
                and self.latest_job_id
                and name == self.latest_job_id
            )

            if size > 0:
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                display = f"{icon}  {name}  ({size_str})"
            else:
                display = f"{icon}  {name}"

            # Добавляем метку для последней распознанной папки
            if is_latest:
                display = f"{display}  ✅ (последний распознанный вариант)"

            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, file_info)

            # Подсвечиваем последнюю папку зелёным
            if is_latest:
                item.setForeground(Qt.darkGreen)
                from PySide6.QtGui import QFont
                font = item.font()
                font.setBold(True)
                item.setFont(font)

            self.files_list.addItem(item)

    def _on_file_double_clicked(self, item: QListWidgetItem):
        """Обработчик двойного клика на файл"""
        file_info = item.data(Qt.UserRole)
        if not file_info:
            return

        if file_info.get("is_dir"):
            children = file_info.get("children", [])
            self.current_path.append(
                {"name": file_info.get("name", ""), "files": self._get_current_files()}
            )
            self._populate_files(children)
            self._update_header()
            self.back_btn.setEnabled(True)
            return

        file_path = file_info.get("path", "")
        if file_path:
            import os

            r2_public = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
            url = f"{r2_public}/{file_path}"
            webbrowser.open(url)

    def _go_back(self):
        """Вернуться в родительскую папку"""
        if not self.current_path:
            return

        prev = self.current_path.pop()
        self._populate_files(prev["files"])
        self._update_header()
        self.back_btn.setEnabled(len(self.current_path) > 0)

    def _update_header(self):
        """Обновить заголовок с текущим путём"""
        if self.current_path:
            path_str = "/".join(p["name"] for p in self.current_path)
            self.header.setText(f"📦 {self.r2_base_url}/{path_str}")
        else:
            self.header.setText(f"📦 {self.r2_base_url}")

    def _get_current_files(self) -> list:
        """Получить текущий список файлов для сохранения в стек"""
        files = []
        for i in range(self.files_list.count()):
            item = self.files_list.item(i)
            file_info = item.data(Qt.UserRole)
            if file_info:
                files.append(file_info)
        return files

    def _collect_all_files(self, files: list, base_path: str = "") -> list:
        """Рекурсивно собрать все файлы (включая вложенные папки)"""
        result = []
        for f in files:
            if f.get("is_dir"):
                children = f.get("children", [])
                folder_name = f.get("name", "")
                new_base = f"{base_path}/{folder_name}" if base_path else folder_name
                result.extend(self._collect_all_files(children, new_base))
            else:
                file_copy = f.copy()
                if base_path:
                    file_copy["rel_path"] = f"{base_path}/{f.get('name', '')}"
                else:
                    file_copy["rel_path"] = f.get("name", "")
                result.append(file_copy)
        return result

    def _download_selected(self):
        """Скачать выбранные файлы"""
        selected = self.files_list.selectedItems()
        if not selected:
            return

        files_to_download = []
        for item in selected:
            file_info = item.data(Qt.UserRole)
            if file_info:
                if file_info.get("is_dir"):
                    children = file_info.get("children", [])
                    folder_name = file_info.get("name", "")
                    files_to_download.extend(
                        self._collect_all_files(children, folder_name)
                    )
                else:
                    file_copy = file_info.copy()
                    file_copy["rel_path"] = file_info.get("name", "")
                    files_to_download.append(file_copy)

        if not files_to_download:
            QMessageBox.information(self, "Скачивание", "Нет файлов для скачивания")
            return

        self._start_download(files_to_download)

    def _download_all(self):
        """Скачать все файлы"""
        current_files = self._get_current_files()
        files_to_download = self._collect_all_files(current_files)

        if not files_to_download:
            QMessageBox.information(self, "Скачивание", "Нет файлов для скачивания")
            return

        self._start_download(files_to_download)

    def _start_download(self, files: list):
        """Начать скачивание файлов"""
        if self.local_folder and self.local_folder.exists():
            target_dir = self.local_folder
        else:
            target_dir = QFileDialog.getExistingDirectory(
                self, "Выберите папку для сохранения", str(Path.home())
            )
            if not target_dir:
                return
            target_dir = Path(target_dir)

        progress = QProgressDialog("Скачивание...", "Отмена", 0, len(files), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        self._worker = R2DownloadWorker(files, target_dir)

        def on_progress(current, total, filename):
            progress.setValue(current)
            progress.setLabelText(f"Скачивание: {filename}")

        def on_finished(success, message):
            progress.close()
            if success:
                QMessageBox.information(self, "Готово", message)
                import subprocess
                import sys

                if sys.platform == "win32":
                    subprocess.Popen(["explorer", str(target_dir)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(target_dir)])
                else:
                    subprocess.Popen(["xdg-open", str(target_dir)])
            else:
                QMessageBox.warning(self, "Ошибка", message)
            self._worker = None

        progress.canceled.connect(self._worker.cancel)
        self._worker.progress.connect(on_progress)
        self._worker.finished.connect(on_finished)
        self._worker.start()

    def _delete_selected(self):
        """Удалить выбранные файлы"""
        selected = self.files_list.selectedItems()
        if not selected:
            return

        files_to_delete = []
        for item in selected:
            file_info = item.data(Qt.UserRole)
            if file_info:
                if file_info.get("is_dir"):
                    children = file_info.get("children", [])
                    folder_name = file_info.get("name", "")
                    files_to_delete.extend(
                        self._collect_all_files(children, folder_name)
                    )
                else:
                    files_to_delete.append(file_info)

        if not files_to_delete:
            QMessageBox.information(self, "Удаление", "Нет файлов для удаления")
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить {len(files_to_delete)} файл(ов)?\n\n"
            "Файлы будут удалены:\n"
            "• С R2 Storage\n"
            "• Из локальной папки (если есть)\n"
            "• Из базы данных Supabase",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog(
            "Удаление...", "Отмена", 0, len(files_to_delete), self
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        self._worker = R2DeleteWorker(files_to_delete, self.node_id)

        def on_progress(current, total, filename):
            progress.setValue(current)
            progress.setLabelText(f"Удаление: {filename}")

        def on_finished(success, message, deleted_keys):
            progress.close()
            self._cleanup_after_delete(deleted_keys)

            if success:
                QMessageBox.information(self, "Готово", message)
                self._refresh_files()
                self.files_changed.emit()
            else:
                QMessageBox.warning(self, "Ошибка", message)

            self._worker = None

        progress.canceled.connect(self._worker.cancel)
        self._worker.progress.connect(on_progress)
        self._worker.finished.connect(on_finished)
        self._worker.start()

    def _cleanup_after_delete(self, deleted_keys: list):
        """Очистить локальные файлы и Supabase после удаления"""
        if not deleted_keys:
            return

        # Удаляем локальные файлы
        from app.gui.folder_settings_dialog import get_projects_dir

        projects_dir = get_projects_dir()
        if projects_dir:
            for r2_key in deleted_keys:
                try:
                    if r2_key.startswith("tree_docs/"):
                        rel_path = r2_key[len("tree_docs/"):]
                    else:
                        rel_path = r2_key

                    local_file = Path(projects_dir) / "cache" / rel_path
                    if local_file.exists():
                        local_file.unlink()
                        logger.info(f"Deleted local file: {local_file}")
                except Exception as e:
                    logger.warning(f"Failed to delete local file {r2_key}: {e}")

        # Удаляем записи из Supabase
        if self.node_id:
            try:
                from app.tree_client import TreeClient

                client = TreeClient()
                node_files = client.get_node_files(self.node_id)
                for nf in node_files:
                    if nf.r2_key in deleted_keys:
                        client.delete_node_file(nf.id)
                        logger.info(f"Deleted node_file record: {nf.id}")
            except Exception as e:
                logger.warning(f"Failed to cleanup Supabase: {e}")

    def _refresh_files(self):
        """Обновить список файлов с R2"""
        if not self.r2_prefix:
            return

        try:
            from rd_adapters.storage import R2SyncStorage as R2Storage

            r2 = R2Storage()
            r2_objects = r2.list_objects_with_metadata(self.r2_prefix)

            if r2_objects:
                parent = self.parent()
                if hasattr(parent, "_build_r2_file_tree"):
                    self.r2_files = parent._build_r2_file_tree(
                        r2_objects, self.r2_prefix
                    )
                else:
                    self.r2_files = []
                    for obj in r2_objects:
                        key = obj.get("Key", "")
                        name = Path(key).name
                        self.r2_files.append(
                            {
                                "name": name,
                                "path": key,
                                "icon": "📄",
                                "is_dir": False,
                                "size": obj.get("Size", 0),
                            }
                        )
            else:
                self.r2_files = []

            self.current_path = []
            self.back_btn.setEnabled(False)
            self._update_header()
            self._populate_files(self.r2_files)

        except Exception as e:
            logger.error(f"Failed to refresh R2 files: {e}")
