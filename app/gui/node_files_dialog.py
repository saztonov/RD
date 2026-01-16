"""Диалог для просмотра файлов узла в Supabase (иерархический вид)"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from app.tree_client import TreeNode

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


class NodeFilesDialog(QDialog):
    """Диалог для отображения файлов узла из Supabase (иерархический вид)"""

    def __init__(self, node: "TreeNode", client, parent=None):
        super().__init__(parent)
        self.node = node
        self.client = client
        self.files: List[dict] = []
        self.latest_job_id: Optional[str] = None

        self.setWindowTitle(f"Файлы узла: {node.name}")
        self.resize(900, 600)
        self._setup_ui()
        self._load_files()

    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)

        # Информация об узле
        info_label = QLabel(
            f"<b>Узел:</b> {self.node.name}<br>"
            f"<b>ID:</b> {self.node.id}<br>"
            f"<b>Тип:</b> {self.node.node_type.value}"
        )
        layout.addWidget(info_label)

        # Дерево файлов
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Имя", "Тип", "Размер", "Создан", "ID"])
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 150)
        self.tree.setColumnWidth(4, 280)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree)

        # Кнопки
        button_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 Обновить")
        self.refresh_btn.clicked.connect(self._load_files)
        button_layout.addWidget(self.refresh_btn)

        self.delete_btn = QPushButton("🗑️ Удалить")
        self.delete_btn.clicked.connect(self._delete_selected)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setStyleSheet("color: #d32f2f;")
        button_layout.addWidget(self.delete_btn)

        button_layout.addStretch()

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

        # Обновление кнопки удаления при выделении
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self):
        """Обработчик изменения выделения"""
        selected = self.tree.selectedItems()
        self.delete_btn.setEnabled(len(selected) > 0)
        if selected:
            self.delete_btn.setText(f"🗑️ Удалить ({len(selected)})")
        else:
            self.delete_btn.setText("🗑️ Удалить")

    def _load_files(self):
        """Загрузить список файлов из Supabase"""
        try:
            self.refresh_btn.setEnabled(False)
            self.refresh_btn.setText("⏳ Загрузка...")

            # Запрос к Supabase через TreeClient
            path = (
                f"/node_files?"
                f"node_id=eq.{self.node.id}&"
                f"select=id,file_type,file_name,r2_key,file_size,mime_type,created_at,metadata&"
                f"order=created_at.desc"
            )

            response = self.client._request("get", path)
            if response and response.status_code == 200:
                self.files = response.json()
                self._load_latest_job_id()
                self._populate_tree()
            else:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Не удалось загрузить файлы: {response.status_code if response else 'нет ответа'}",
                )

        except Exception as e:
            logger.error(f"Failed to load node files: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки файлов:\n{e}")
        finally:
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("🔄 Обновить")

    def _load_latest_job_id(self):
        """Загрузить ID последнего OCR запуска"""
        try:
            from rd_adapters.storage import R2SyncStorage as R2Storage

            r2 = R2Storage()
            latest_run_key = f"tree_docs/{self.node.id}/latest_ocr_run.json"
            content = r2.download_text(latest_run_key)
            if content:
                data = json.loads(content)
                self.latest_job_id = data.get("job_id")
        except Exception as e:
            logger.debug(f"Failed to get latest OCR job_id: {e}")
            self.latest_job_id = None

    def _populate_tree(self):
        """Заполнить дерево данными"""
        self.tree.clear()

        # Группируем файлы по папкам на основе r2_key
        # Структура: tree_docs/{node_id}/ocr_runs/{job_id}/file.ext
        #            tree_docs/{node_id}/document.pdf

        folders: Dict[str, List[dict]] = defaultdict(list)
        root_files: List[dict] = []

        for file_data in self.files:
            r2_key = file_data.get("r2_key", "")
            # Извлекаем относительный путь от node_id
            prefix = f"tree_docs/{self.node.id}/"
            if r2_key.startswith(prefix):
                rel_path = r2_key[len(prefix):]
            else:
                rel_path = r2_key

            parts = rel_path.split("/")
            if len(parts) > 1:
                # Файл в подпапке
                folder_key = "/".join(parts[:-1])  # ocr_runs/{job_id}
                folders[folder_key].append(file_data)
            else:
                # Корневой файл
                root_files.append(file_data)

        # Добавляем корневые файлы
        for file_data in root_files:
            item = self._create_file_item(file_data)
            self.tree.addTopLevelItem(item)

        # Добавляем папки и их содержимое
        # Сортируем папки: ocr_runs в конце, внутри ocr_runs - по дате
        sorted_folders = sorted(folders.keys())

        # Группируем по первому уровню (ocr_runs, etc.)
        top_folders: Dict[str, Dict[str, List[dict]]] = defaultdict(dict)
        for folder_key, files in folders.items():
            parts = folder_key.split("/")
            if len(parts) >= 2:
                top_folder = parts[0]  # ocr_runs
                sub_folder = "/".join(parts[1:])  # {job_id}
                top_folders[top_folder][sub_folder] = files
            else:
                # Одноуровневая папка
                top_folders[folder_key][""] = files

        for top_folder_name in sorted(top_folders.keys()):
            sub_folders = top_folders[top_folder_name]

            # Создаём родительский элемент папки
            folder_item = QTreeWidgetItem()
            folder_item.setText(0, f"📁 {top_folder_name}")
            folder_item.setData(0, Qt.UserRole, {"is_folder": True, "name": top_folder_name})

            if top_folder_name == "ocr_runs":
                # Сортируем job_id по дате создания файлов внутри (последние сверху)
                sub_items = []
                for sub_folder_name, files in sub_folders.items():
                    if sub_folder_name:
                        # Получаем дату первого файла в папке
                        earliest_date = min(
                            (f.get("created_at", "") for f in files),
                            default=""
                        )
                        sub_items.append((sub_folder_name, files, earliest_date))

                # Сортируем по дате (новые сверху)
                sub_items.sort(key=lambda x: x[2], reverse=True)

                for sub_folder_name, files, _ in sub_items:
                    is_latest = self.latest_job_id and sub_folder_name == self.latest_job_id

                    sub_folder_item = QTreeWidgetItem()
                    display_name = f"📁 {sub_folder_name}"
                    if is_latest:
                        display_name = f"📁 {sub_folder_name}  ✅ (последний распознанный вариант)"
                        sub_folder_item.setForeground(0, Qt.darkGreen)
                        font = sub_folder_item.font(0)
                        font.setBold(True)
                        sub_folder_item.setFont(0, font)

                    sub_folder_item.setText(0, display_name)
                    sub_folder_item.setData(0, Qt.UserRole, {"is_folder": True, "name": sub_folder_name})

                    # Добавляем файлы в подпапку
                    for file_data in files:
                        file_item = self._create_file_item(file_data)
                        sub_folder_item.addChild(file_item)

                    folder_item.addChild(sub_folder_item)
            else:
                # Обычная папка - добавляем файлы напрямую
                for sub_folder_name, files in sub_folders.items():
                    if sub_folder_name:
                        sub_folder_item = QTreeWidgetItem()
                        sub_folder_item.setText(0, f"📁 {sub_folder_name}")
                        sub_folder_item.setData(0, Qt.UserRole, {"is_folder": True, "name": sub_folder_name})
                        for file_data in files:
                            file_item = self._create_file_item(file_data)
                            sub_folder_item.addChild(file_item)
                        folder_item.addChild(sub_folder_item)
                    else:
                        # Файлы в первом уровне папки
                        for file_data in files:
                            file_item = self._create_file_item(file_data)
                            folder_item.addChild(file_item)

            self.tree.addTopLevelItem(folder_item)

        # Раскрываем папку ocr_runs по умолчанию
        self.tree.expandAll()

        # Установить заголовок с количеством
        self.setWindowTitle(f"Файлы узла: {self.node.name} ({len(self.files)})")

    def _create_file_item(self, file_data: dict) -> QTreeWidgetItem:
        """Создать элемент дерева для файла"""
        item = QTreeWidgetItem()

        # Имя файла с иконкой
        file_name = file_data.get("file_name", "")
        file_type = file_data.get("file_type", "")
        icon = FILE_TYPE_ICONS.get(file_type, "📄")
        item.setText(0, f"{icon} {file_name}")

        # Тип файла
        item.setText(1, file_type)

        # Размер файла
        file_size = file_data.get("file_size", 0)
        item.setText(2, self._format_size(file_size))

        # Дата создания
        created_at = file_data.get("created_at", "")
        item.setText(3, self._format_datetime(created_at))

        # ID файла
        file_id = file_data.get("id", "")
        item.setText(4, file_id)

        # Сохраняем данные файла
        item.setData(0, Qt.UserRole, file_data)

        return item

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

    def _delete_selected(self):
        """Удалить выбранные файлы"""
        selected = self.tree.selectedItems()
        if not selected:
            return

        # Собираем файлы для удаления (включая все файлы из выбранных папок)
        files_to_delete: List[dict] = []

        def collect_files(item: QTreeWidgetItem):
            data = item.data(0, Qt.UserRole)
            if data:
                if data.get("is_folder"):
                    # Это папка - собираем все файлы внутри
                    for i in range(item.childCount()):
                        collect_files(item.child(i))
                elif data.get("id"):
                    # Это файл
                    files_to_delete.append(data)

        for item in selected:
            collect_files(item)

        if not files_to_delete:
            QMessageBox.information(self, "Удаление", "Нет файлов для удаления")
            return

        # Подтверждение
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить {len(files_to_delete)} файл(ов) из Supabase?\n\n"
            "Это действие нельзя отменить.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        # Удаляем файлы
        deleted_count = 0
        errors = []

        for file_data in files_to_delete:
            file_id = file_data.get("id")
            file_name = file_data.get("file_name", "")
            try:
                # Удаляем из Supabase
                response = self.client._request("delete", f"/node_files?id=eq.{file_id}")
                if response and response.status_code in (200, 204):
                    deleted_count += 1
                    logger.info(f"Deleted node_file: {file_id} ({file_name})")
                else:
                    errors.append(f"{file_name}: HTTP {response.status_code if response else 'no response'}")
            except Exception as e:
                errors.append(f"{file_name}: {e}")
                logger.error(f"Failed to delete node_file {file_id}: {e}")

        # Показываем результат
        if errors:
            QMessageBox.warning(
                self,
                "Частичное удаление",
                f"Удалено {deleted_count} файлов.\n\nОшибки:\n" + "\n".join(errors[:5])
            )
        else:
            QMessageBox.information(
                self,
                "Готово",
                f"Удалено {deleted_count} файлов."
            )

        # Обновляем список
        self._load_files()
