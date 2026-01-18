"""Диалог для просмотра информации о хранении документа в R2 и Supabase"""
from __future__ import annotations

import json
import logging
import os
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from apps.rd_desktop.tree_client import TreeClient, TreeNode

logger = logging.getLogger(__name__)

# Иконки для типов файлов
FILE_TYPE_ICONS = {
    "pdf": "📕",
    "annotation": "📋",
    "crop": "🖼️",
    "image": "🖼️",
    "ocr_html": "🌐",
    "result_json": "📋",
    "result_md": "📝",
    "result_zip": "📦",
    "crops_folder": "📁",
    "qa_manifest": "❓",
}

# Иконки для расширений файлов
FILE_ICONS = {
    "pdf": "📕",
    "json": "📋",
    "md": "📝",
    "png": "🖼️",
    "jpg": "🖼️",
    "jpeg": "🖼️",
    "webp": "🖼️",
    "zip": "📦",
    "html": "🌐",
}

# Иконки для статусов jobs
JOB_STATUS_ICONS = {
    "draft": "📝",
    "queued": "⏳",
    "processing": "🔄",
    "done": "✅",
    "error": "❌",
}


class StorageInfoDialog(QDialog):
    """
    Объединённый диалог для просмотра и управления файлами документа
    в R2 Storage и Supabase.
    """

    def __init__(self, node: "TreeNode", client: "TreeClient", parent=None):
        super().__init__(parent)
        self.node = node
        self.client = client
        self.r2_files: List[dict] = []
        self.node_files: List[dict] = []
        self.jobs: List[dict] = []
        self.latest_job_id: Optional[str] = None
        self.current_r2_path: List[dict] = []
        self._download_worker = None
        self._delete_worker = None

        self.setWindowTitle(f"R2/Supabase: {node.name}")
        self.resize(900, 700)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)

        # Заголовок с информацией о документе
        info_group = QGroupBox("Информация о документе")
        info_layout = QVBoxLayout(info_group)

        r2_key = self.node.attributes.get("r2_key", "")
        info_label = QLabel(
            f"<b>Документ:</b> {self.node.name}<br>"
            f"<b>Node ID:</b> <code>{self.node.id}</code><br>"
            f"<b>R2 Key:</b> <code>{r2_key}</code>"
        )
        info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addWidget(info_label)
        layout.addWidget(info_group)

        # Вкладки
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Вкладка R2 Storage
        self.r2_tab = QWidget()
        self._setup_r2_tab()
        self.tabs.addTab(self.r2_tab, "☁️ R2 Storage")

        # Вкладка Supabase
        self.supabase_tab = QWidget()
        self._setup_supabase_tab()
        self.tabs.addTab(self.supabase_tab, "🗄️ Supabase")

        # Кнопки внизу
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _setup_r2_tab(self):
        """Настройка вкладки R2 Storage"""
        layout = QVBoxLayout(self.r2_tab)

        # Навигация
        nav_layout = QHBoxLayout()

        self.r2_back_btn = QPushButton("⬅️ Назад")
        self.r2_back_btn.setMaximumWidth(80)
        self.r2_back_btn.clicked.connect(self._r2_go_back)
        self.r2_back_btn.setEnabled(False)
        nav_layout.addWidget(self.r2_back_btn)

        self.r2_header = QLabel("📦 Загрузка...")
        self.r2_header.setWordWrap(True)
        self.r2_header.setStyleSheet("font-weight: bold; padding: 5px;")
        nav_layout.addWidget(self.r2_header, 1)

        layout.addLayout(nav_layout)

        # Список файлов
        self.r2_list = QListWidget()
        self.r2_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.r2_list.itemDoubleClicked.connect(self._r2_on_double_click)
        self.r2_list.itemSelectionChanged.connect(self._r2_on_selection_changed)
        layout.addWidget(self.r2_list)

        # Кнопки действий
        actions_layout = QHBoxLayout()

        self.r2_download_btn = QPushButton("📥 Скачать")
        self.r2_download_btn.clicked.connect(self._r2_download_selected)
        self.r2_download_btn.setEnabled(False)
        actions_layout.addWidget(self.r2_download_btn)

        self.r2_download_all_btn = QPushButton("📥 Скачать всё")
        self.r2_download_all_btn.clicked.connect(self._r2_download_all)
        actions_layout.addWidget(self.r2_download_all_btn)

        actions_layout.addStretch()

        self.r2_delete_btn = QPushButton("🗑️ Удалить")
        self.r2_delete_btn.clicked.connect(self._r2_delete_selected)
        self.r2_delete_btn.setEnabled(False)
        self.r2_delete_btn.setStyleSheet("color: #d32f2f;")
        actions_layout.addWidget(self.r2_delete_btn)

        layout.addLayout(actions_layout)

        # Подсказка
        hint = QLabel("💡 Дважды кликните для открытия папки или файла в браузере.")
        hint.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(hint)

    def _setup_supabase_tab(self):
        """Настройка вкладки Supabase"""
        layout = QVBoxLayout(self.supabase_tab)

        # Разделитель на две части
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter)

        # Верхняя часть: node_files
        files_group = QGroupBox("Файлы (node_files)")
        files_layout = QVBoxLayout(files_group)

        self.sb_files_tree = QTreeWidget()
        self.sb_files_tree.setHeaderLabels(["Имя", "Тип", "Размер", "Создан", "ID"])
        self.sb_files_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.sb_files_tree.setColumnWidth(0, 300)
        self.sb_files_tree.setColumnWidth(1, 100)
        self.sb_files_tree.setColumnWidth(2, 80)
        self.sb_files_tree.setColumnWidth(3, 150)
        self.sb_files_tree.setColumnWidth(4, 280)
        self.sb_files_tree.setAlternatingRowColors(True)
        self.sb_files_tree.itemSelectionChanged.connect(self._sb_on_selection_changed)
        files_layout.addWidget(self.sb_files_tree)

        # Кнопки для node_files
        files_btn_layout = QHBoxLayout()
        self.sb_delete_files_btn = QPushButton("🗑️ Удалить выбранные")
        self.sb_delete_files_btn.clicked.connect(self._sb_delete_selected_files)
        self.sb_delete_files_btn.setEnabled(False)
        self.sb_delete_files_btn.setStyleSheet("color: #d32f2f;")
        files_btn_layout.addWidget(self.sb_delete_files_btn)
        files_btn_layout.addStretch()
        files_layout.addLayout(files_btn_layout)

        splitter.addWidget(files_group)

        # Нижняя часть: jobs
        jobs_group = QGroupBox("OCR задачи (jobs)")
        jobs_layout = QVBoxLayout(jobs_group)

        self.sb_jobs_tree = QTreeWidget()
        self.sb_jobs_tree.setHeaderLabels(["Job ID", "Статус", "Документ", "Создан", "Завершён"])
        self.sb_jobs_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.sb_jobs_tree.setColumnWidth(0, 280)
        self.sb_jobs_tree.setColumnWidth(1, 100)
        self.sb_jobs_tree.setColumnWidth(2, 150)
        self.sb_jobs_tree.setColumnWidth(3, 150)
        self.sb_jobs_tree.setColumnWidth(4, 150)
        self.sb_jobs_tree.setAlternatingRowColors(True)
        self.sb_jobs_tree.itemSelectionChanged.connect(self._sb_on_jobs_selection_changed)
        jobs_layout.addWidget(self.sb_jobs_tree)

        # Кнопки для jobs
        jobs_btn_layout = QHBoxLayout()
        self.sb_delete_jobs_btn = QPushButton("🗑️ Удалить выбранные jobs")
        self.sb_delete_jobs_btn.clicked.connect(self._sb_delete_selected_jobs)
        self.sb_delete_jobs_btn.setEnabled(False)
        self.sb_delete_jobs_btn.setStyleSheet("color: #d32f2f;")
        jobs_btn_layout.addWidget(self.sb_delete_jobs_btn)
        jobs_btn_layout.addStretch()
        jobs_layout.addLayout(jobs_btn_layout)

        splitter.addWidget(jobs_group)

        # Подсказка
        hint = QLabel("💡 Удаление записей из Supabase не удаляет файлы с R2.")
        hint.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(hint)

    def _load_data(self):
        """Загрузить все данные"""
        self._load_r2_files()
        self._load_supabase_data()

    def _load_r2_files(self):
        """Загрузить файлы с R2"""
        from rd_adapters.storage import R2SyncStorage as R2Storage

        try:
            r2 = R2Storage()
            r2_prefix = f"tree_docs/{self.node.id}/"

            r2_objects = r2.list_objects_with_metadata(r2_prefix)

            if r2_objects:
                self.r2_files = self._build_file_tree(r2_objects, r2_prefix)
            else:
                self.r2_files = []

            # Получаем последний job_id
            self._load_latest_job_id()

            # Обновляем заголовок
            r2_public = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
            self.r2_header.setText(f"📦 {r2_public}/{r2_prefix}")

            # Отображаем файлы
            self._r2_populate_list(self.r2_files)

        except Exception as e:
            logger.error(f"Failed to load R2 files: {e}")
            self.r2_header.setText(f"❌ Ошибка загрузки: {e}")

    def _load_latest_job_id(self):
        """Загрузить ID последнего OCR запуска"""
        from rd_adapters.storage import R2SyncStorage as R2Storage

        try:
            r2 = R2Storage()
            latest_run_key = f"tree_docs/{self.node.id}/latest_ocr_run.json"
            content = r2.download_text(latest_run_key)
            if content:
                data = json.loads(content)
                self.latest_job_id = data.get("job_id")
        except Exception as e:
            logger.debug(f"Failed to get latest OCR job_id: {e}")
            self.latest_job_id = None

    def _build_file_tree(self, r2_objects: List[dict], prefix: str) -> List[dict]:
        """Построить дерево файлов из списка R2 объектов"""
        folders: Dict[str, list] = defaultdict(list)
        files = []

        for obj in r2_objects:
            key = obj.get("Key", "")
            if not key.startswith(prefix):
                continue

            rel_path = key[len(prefix):]
            if not rel_path:
                continue

            parts = rel_path.split("/")
            if len(parts) == 1:
                ext = rel_path.split(".")[-1].lower() if "." in rel_path else ""
                icon = FILE_ICONS.get(ext, "📄")
                files.append({
                    "name": rel_path,
                    "path": key,
                    "icon": icon,
                    "is_dir": False,
                    "size": obj.get("Size", 0),
                })
            else:
                folder_name = parts[0]
                folders[folder_name].append(obj)

        result = []

        for folder_name, folder_objects in sorted(folders.items()):
            children = self._build_file_tree(folder_objects, f"{prefix}{folder_name}/")
            result.append({
                "name": folder_name,
                "icon": "📁",
                "is_dir": True,
                "children": children,
            })

        result.extend(sorted(files, key=lambda x: x["name"]))
        return result

    def _r2_populate_list(self, files: List[dict]):
        """Заполнить список R2 файлов"""
        self.r2_list.clear()

        inside_ocr_runs = self._r2_is_inside_ocr_runs()

        for file_info in files:
            icon = file_info.get("icon", "📄")
            name = file_info.get("name", "")
            size = file_info.get("size", 0)
            is_dir = file_info.get("is_dir", False)

            is_latest = (
                inside_ocr_runs
                and is_dir
                and self.latest_job_id
                and name == self.latest_job_id
            )

            if size > 0:
                size_str = self._format_size(size)
                display = f"{icon}  {name}  ({size_str})"
            else:
                display = f"{icon}  {name}"

            if is_latest:
                display = f"{display}  ✅ (последний)"

            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, file_info)

            if is_latest:
                item.setForeground(Qt.darkGreen)
                font = item.font()
                font.setBold(True)
                item.setFont(font)

            self.r2_list.addItem(item)

    def _r2_is_inside_ocr_runs(self) -> bool:
        """Проверить, находимся ли внутри папки ocr_runs"""
        return any(p.get("name") == "ocr_runs" for p in self.current_r2_path)

    def _r2_on_double_click(self, item: QListWidgetItem):
        """Обработчик двойного клика в R2 списке"""
        file_info = item.data(Qt.UserRole)
        if not file_info:
            return

        if file_info.get("is_dir"):
            children = file_info.get("children", [])
            self.current_r2_path.append({
                "name": file_info.get("name", ""),
                "files": self._r2_get_current_files()
            })
            self._r2_populate_list(children)
            self._r2_update_header()
            self.r2_back_btn.setEnabled(True)
            return

        file_path = file_info.get("path", "")
        if file_path:
            r2_public = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
            url = f"{r2_public}/{file_path}"
            webbrowser.open(url)

    def _r2_go_back(self):
        """Вернуться в родительскую папку R2"""
        if not self.current_r2_path:
            return

        prev = self.current_r2_path.pop()
        self._r2_populate_list(prev["files"])
        self._r2_update_header()
        self.r2_back_btn.setEnabled(len(self.current_r2_path) > 0)

    def _r2_update_header(self):
        """Обновить заголовок R2 с текущим путём"""
        r2_public = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
        base_prefix = f"tree_docs/{self.node.id}/"

        if self.current_r2_path:
            path_str = "/".join(p["name"] for p in self.current_r2_path)
            self.r2_header.setText(f"📦 {r2_public}/{base_prefix}{path_str}/")
        else:
            self.r2_header.setText(f"📦 {r2_public}/{base_prefix}")

    def _r2_get_current_files(self) -> List[dict]:
        """Получить текущий список файлов R2"""
        files = []
        for i in range(self.r2_list.count()):
            item = self.r2_list.item(i)
            file_info = item.data(Qt.UserRole)
            if file_info:
                files.append(file_info)
        return files

    def _r2_on_selection_changed(self):
        """Обработчик изменения выделения в R2"""
        selected = self.r2_list.selectedItems()
        has_selection = len(selected) > 0
        self.r2_download_btn.setEnabled(has_selection)
        self.r2_delete_btn.setEnabled(has_selection)

        if has_selection:
            self.r2_download_btn.setText(f"📥 Скачать ({len(selected)})")
            self.r2_delete_btn.setText(f"🗑️ Удалить ({len(selected)})")
        else:
            self.r2_download_btn.setText("📥 Скачать")
            self.r2_delete_btn.setText("🗑️ Удалить")

    def _r2_collect_all_files(self, files: List[dict], base_path: str = "") -> List[dict]:
        """Рекурсивно собрать все файлы R2"""
        result = []
        for f in files:
            if f.get("is_dir"):
                children = f.get("children", [])
                folder_name = f.get("name", "")
                new_base = f"{base_path}/{folder_name}" if base_path else folder_name
                result.extend(self._r2_collect_all_files(children, new_base))
            else:
                file_copy = f.copy()
                if base_path:
                    file_copy["rel_path"] = f"{base_path}/{f.get('name', '')}"
                else:
                    file_copy["rel_path"] = f.get("name", "")
                result.append(file_copy)
        return result

    def _r2_download_selected(self):
        """Скачать выбранные файлы с R2"""
        selected = self.r2_list.selectedItems()
        if not selected:
            return

        files_to_download = []
        for item in selected:
            file_info = item.data(Qt.UserRole)
            if file_info:
                if file_info.get("is_dir"):
                    children = file_info.get("children", [])
                    folder_name = file_info.get("name", "")
                    files_to_download.extend(self._r2_collect_all_files(children, folder_name))
                else:
                    file_copy = file_info.copy()
                    file_copy["rel_path"] = file_info.get("name", "")
                    files_to_download.append(file_copy)

        if files_to_download:
            self._r2_start_download(files_to_download)

    def _r2_download_all(self):
        """Скачать все файлы с R2"""
        current_files = self._r2_get_current_files()
        files_to_download = self._r2_collect_all_files(current_files)

        if files_to_download:
            self._r2_start_download(files_to_download)

    def _r2_start_download(self, files: List[dict]):
        """Начать скачивание файлов с R2"""
        from apps.rd_desktop.gui.r2_viewer.download_worker import R2DownloadWorker

        target_dir = QFileDialog.getExistingDirectory(
            self, "Выберите папку для сохранения", str(Path.home())
        )
        if not target_dir:
            return

        target_dir = Path(target_dir)

        progress = QProgressDialog("Скачивание...", "Отмена", 0, len(files), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        self._download_worker = R2DownloadWorker(files, target_dir)

        def on_progress(current, total, filename):
            progress.setValue(current)
            progress.setLabelText(f"Скачивание: {filename}")

        def on_finished(success, message):
            progress.close()
            if success:
                QMessageBox.information(self, "Готово", message)
            else:
                QMessageBox.warning(self, "Ошибка", message)
            self._download_worker = None

        progress.canceled.connect(self._download_worker.cancel)
        self._download_worker.progress.connect(on_progress)
        self._download_worker.finished.connect(on_finished)
        self._download_worker.start()

    def _r2_delete_selected(self):
        """Удалить выбранные файлы с R2"""
        from apps.rd_desktop.gui.r2_viewer.delete_worker import R2DeleteWorker

        selected = self.r2_list.selectedItems()
        if not selected:
            return

        files_to_delete = []
        for item in selected:
            file_info = item.data(Qt.UserRole)
            if file_info:
                if file_info.get("is_dir"):
                    children = file_info.get("children", [])
                    folder_name = file_info.get("name", "")
                    files_to_delete.extend(self._r2_collect_all_files(children, folder_name))
                else:
                    files_to_delete.append(file_info)

        if not files_to_delete:
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить {len(files_to_delete)} файл(ов)?\n\n"
            "Файлы будут удалены:\n"
            "• С R2 Storage\n"
            "• Из базы данных Supabase (node_files)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog("Удаление...", "Отмена", 0, len(files_to_delete), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        self._delete_worker = R2DeleteWorker(files_to_delete, self.node.id)

        def on_progress(current, total, filename):
            progress.setValue(current)
            progress.setLabelText(f"Удаление: {filename}")

        def on_finished(success, message, deleted_keys):
            progress.close()
            self._cleanup_after_r2_delete(deleted_keys)

            if success:
                QMessageBox.information(self, "Готово", message)
            else:
                QMessageBox.warning(self, "Ошибка", message)

            self._delete_worker = None
            self._load_data()

        progress.canceled.connect(self._delete_worker.cancel)
        self._delete_worker.progress.connect(on_progress)
        self._delete_worker.finished.connect(on_finished)
        self._delete_worker.start()

    def _cleanup_after_r2_delete(self, deleted_keys: List[str]):
        """Очистить записи Supabase после удаления с R2"""
        if not deleted_keys or not self.node.id:
            return

        try:
            node_files = self.client.get_node_files(self.node.id)
            for nf in node_files:
                if nf.r2_key in deleted_keys:
                    self.client.delete_node_file(nf.id)
                    logger.info(f"Deleted node_file record: {nf.id}")
        except Exception as e:
            logger.warning(f"Failed to cleanup Supabase after R2 delete: {e}")

    def _load_supabase_data(self):
        """Загрузить данные из Supabase"""
        self._load_node_files()
        self._load_jobs()

    def _load_node_files(self):
        """Загрузить записи node_files"""
        try:
            path = (
                f"/node_files?"
                f"node_id=eq.{self.node.id}&"
                f"select=id,file_type,file_name,r2_key,file_size,mime_type,created_at,metadata&"
                f"order=created_at.desc"
            )
            response = self.client._request("get", path)
            if response and response.status_code == 200:
                self.node_files = response.json()
                self._populate_node_files_tree()
        except Exception as e:
            logger.error(f"Failed to load node_files: {e}")

    def _load_jobs(self):
        """Загрузить OCR jobs для узла"""
        try:
            path = (
                f"/jobs?"
                f"node_id=eq.{self.node.id}&"
                f"select=id,status,document_name,created_at,completed_at&"
                f"order=created_at.desc"
            )
            response = self.client._request("get", path)
            if response and response.status_code == 200:
                self.jobs = response.json()
                self._populate_jobs_tree()
        except Exception as e:
            logger.error(f"Failed to load jobs: {e}")

    def _populate_node_files_tree(self):
        """Заполнить дерево node_files"""
        self.sb_files_tree.clear()

        folders: Dict[str, List[dict]] = defaultdict(list)
        root_files: List[dict] = []

        for file_data in self.node_files:
            r2_key = file_data.get("r2_key", "")
            prefix = f"tree_docs/{self.node.id}/"
            if r2_key.startswith(prefix):
                rel_path = r2_key[len(prefix):]
            else:
                rel_path = r2_key

            parts = rel_path.split("/")
            if len(parts) > 1:
                folder_key = "/".join(parts[:-1])
                folders[folder_key].append(file_data)
            else:
                root_files.append(file_data)

        # Добавляем корневые файлы
        for file_data in root_files:
            item = self._create_node_file_item(file_data)
            self.sb_files_tree.addTopLevelItem(item)

        # Группируем по первому уровню
        top_folders: Dict[str, Dict[str, List[dict]]] = defaultdict(dict)
        for folder_key, files in folders.items():
            parts = folder_key.split("/")
            if len(parts) >= 2:
                top_folder = parts[0]
                sub_folder = "/".join(parts[1:])
                top_folders[top_folder][sub_folder] = files
            else:
                top_folders[folder_key][""] = files

        for top_folder_name in sorted(top_folders.keys()):
            sub_folders = top_folders[top_folder_name]

            folder_item = QTreeWidgetItem()
            folder_item.setText(0, f"📁 {top_folder_name}")
            folder_item.setData(0, Qt.UserRole, {"is_folder": True, "name": top_folder_name})

            if top_folder_name == "ocr_runs":
                sub_items = []
                for sub_folder_name, files in sub_folders.items():
                    if sub_folder_name:
                        earliest_date = min(
                            (f.get("created_at", "") for f in files),
                            default=""
                        )
                        sub_items.append((sub_folder_name, files, earliest_date))

                sub_items.sort(key=lambda x: x[2], reverse=True)

                for sub_folder_name, files, _ in sub_items:
                    is_latest = self.latest_job_id and sub_folder_name == self.latest_job_id

                    sub_folder_item = QTreeWidgetItem()
                    display_name = f"📁 {sub_folder_name}"
                    if is_latest:
                        display_name = f"📁 {sub_folder_name}  ✅ (последний)"
                        sub_folder_item.setForeground(0, Qt.darkGreen)
                        font = sub_folder_item.font(0)
                        font.setBold(True)
                        sub_folder_item.setFont(0, font)

                    sub_folder_item.setText(0, display_name)
                    sub_folder_item.setData(0, Qt.UserRole, {"is_folder": True, "name": sub_folder_name})

                    for file_data in files:
                        file_item = self._create_node_file_item(file_data)
                        sub_folder_item.addChild(file_item)

                    folder_item.addChild(sub_folder_item)
            else:
                for sub_folder_name, files in sub_folders.items():
                    if sub_folder_name:
                        sub_folder_item = QTreeWidgetItem()
                        sub_folder_item.setText(0, f"📁 {sub_folder_name}")
                        sub_folder_item.setData(0, Qt.UserRole, {"is_folder": True, "name": sub_folder_name})
                        for file_data in files:
                            file_item = self._create_node_file_item(file_data)
                            sub_folder_item.addChild(file_item)
                        folder_item.addChild(sub_folder_item)
                    else:
                        for file_data in files:
                            file_item = self._create_node_file_item(file_data)
                            folder_item.addChild(file_item)

            self.sb_files_tree.addTopLevelItem(folder_item)

        self.sb_files_tree.expandAll()

    def _create_node_file_item(self, file_data: dict) -> QTreeWidgetItem:
        """Создать элемент дерева для node_file"""
        item = QTreeWidgetItem()

        file_name = file_data.get("file_name", "")
        file_type = file_data.get("file_type", "")
        icon = FILE_TYPE_ICONS.get(file_type, "📄")
        item.setText(0, f"{icon} {file_name}")
        item.setText(1, file_type)
        item.setText(2, self._format_size(file_data.get("file_size", 0)))
        item.setText(3, self._format_datetime(file_data.get("created_at", "")))
        item.setText(4, file_data.get("id", ""))
        item.setData(0, Qt.UserRole, file_data)

        return item

    def _populate_jobs_tree(self):
        """Заполнить дерево jobs"""
        self.sb_jobs_tree.clear()

        for job_data in self.jobs:
            item = QTreeWidgetItem()

            job_id = job_data.get("id", "")
            status = job_data.get("status", "")
            doc_name = job_data.get("document_name", "")
            created_at = job_data.get("created_at", "")
            completed_at = job_data.get("completed_at", "")

            is_latest = self.latest_job_id and job_id == self.latest_job_id

            status_icon = JOB_STATUS_ICONS.get(status, "❓")
            display_id = job_id
            if is_latest:
                display_id = f"{job_id}  ✅ (последний)"

            item.setText(0, display_id)
            item.setText(1, f"{status_icon} {status}")
            item.setText(2, doc_name)
            item.setText(3, self._format_datetime(created_at))
            item.setText(4, self._format_datetime(completed_at))
            item.setData(0, Qt.UserRole, job_data)

            if is_latest:
                item.setForeground(0, Qt.darkGreen)
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)

            self.sb_jobs_tree.addTopLevelItem(item)

    def _sb_on_selection_changed(self):
        """Обработчик изменения выделения в node_files"""
        selected = self.sb_files_tree.selectedItems()
        self.sb_delete_files_btn.setEnabled(len(selected) > 0)
        if selected:
            self.sb_delete_files_btn.setText(f"🗑️ Удалить выбранные ({len(selected)})")
        else:
            self.sb_delete_files_btn.setText("🗑️ Удалить выбранные")

    def _sb_on_jobs_selection_changed(self):
        """Обработчик изменения выделения в jobs"""
        selected = self.sb_jobs_tree.selectedItems()
        self.sb_delete_jobs_btn.setEnabled(len(selected) > 0)
        if selected:
            self.sb_delete_jobs_btn.setText(f"🗑️ Удалить выбранные jobs ({len(selected)})")
        else:
            self.sb_delete_jobs_btn.setText("🗑️ Удалить выбранные jobs")

    def _sb_delete_selected_files(self):
        """Удалить выбранные записи node_files"""
        selected = self.sb_files_tree.selectedItems()
        if not selected:
            return

        files_to_delete: List[dict] = []

        def collect_files(item: QTreeWidgetItem):
            data = item.data(0, Qt.UserRole)
            if data:
                if data.get("is_folder"):
                    for i in range(item.childCount()):
                        collect_files(item.child(i))
                elif data.get("id"):
                    files_to_delete.append(data)

        for item in selected:
            collect_files(item)

        if not files_to_delete:
            QMessageBox.information(self, "Удаление", "Нет файлов для удаления")
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить {len(files_to_delete)} запись(ей) из Supabase?\n\n"
            "Это НЕ удалит файлы с R2!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        deleted_count = 0
        errors = []

        for file_data in files_to_delete:
            file_id = file_data.get("id")
            file_name = file_data.get("file_name", "")
            try:
                response = self.client._request("delete", f"/node_files?id=eq.{file_id}")
                if response and response.status_code in (200, 204):
                    deleted_count += 1
                else:
                    errors.append(f"{file_name}: HTTP {response.status_code if response else 'no response'}")
            except Exception as e:
                errors.append(f"{file_name}: {e}")

        if errors:
            QMessageBox.warning(
                self, "Частичное удаление",
                f"Удалено {deleted_count} записей.\n\nОшибки:\n" + "\n".join(errors[:5])
            )
        else:
            QMessageBox.information(self, "Готово", f"Удалено {deleted_count} записей.")

        self._load_node_files()

    def _sb_delete_selected_jobs(self):
        """Удалить выбранные jobs"""
        selected = self.sb_jobs_tree.selectedItems()
        if not selected:
            return

        jobs_to_delete = []
        for item in selected:
            data = item.data(0, Qt.UserRole)
            if data and data.get("id"):
                jobs_to_delete.append(data)

        if not jobs_to_delete:
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить {len(jobs_to_delete)} OCR задач(у)?\n\n"
            "Это НЕ удалит файлы с R2!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        deleted_count = 0
        errors = []

        for job_data in jobs_to_delete:
            job_id = job_data.get("id")
            try:
                response = self.client._request("delete", f"/jobs?id=eq.{job_id}")
                if response and response.status_code in (200, 204):
                    deleted_count += 1
                else:
                    errors.append(f"{job_id}: HTTP {response.status_code if response else 'no response'}")
            except Exception as e:
                errors.append(f"{job_id}: {e}")

        if errors:
            QMessageBox.warning(
                self, "Частичное удаление",
                f"Удалено {deleted_count} задач.\n\nОшибки:\n" + "\n".join(errors[:5])
            )
        else:
            QMessageBox.information(self, "Готово", f"Удалено {deleted_count} задач.")

        self._load_jobs()

    def _format_size(self, size_bytes: int) -> str:
        """Форматировать размер файла"""
        if size_bytes == 0:
            return "0 B"
        elif size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def _format_datetime(self, dt_str: str) -> str:
        """Форматировать дату/время"""
        if not dt_str:
            return ""
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return dt_str
