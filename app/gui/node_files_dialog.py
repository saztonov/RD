"""Диалог для просмотра файлов узла в Supabase"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from app.tree_client import TreeNode

logger = logging.getLogger(__name__)


class NodeFilesDialog(QDialog):
    """Диалог для отображения файлов узла из Supabase"""

    def __init__(self, node: "TreeNode", client, parent=None):
        super().__init__(parent)
        self.node = node
        self.client = client
        self.files = []

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

        # Таблица файлов
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Тип", "Имя файла", "R2 ключ", "Размер", "MIME", "Создан"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 250)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 160)
        layout.addWidget(self.table)

        # Кнопки
        button_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 Обновить")
        self.refresh_btn.clicked.connect(self._load_files)
        button_layout.addWidget(self.refresh_btn)

        button_layout.addStretch()

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

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
                self._populate_table()
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

    def _populate_table(self):
        """Заполнить таблицу данными"""
        self.table.setRowCount(len(self.files))

        for row, file_data in enumerate(self.files):
            # Тип файла
            file_type = file_data.get("file_type", "")
            type_item = QTableWidgetItem(file_type)
            self.table.setItem(row, 0, type_item)

            # Имя файла
            file_name = file_data.get("file_name", "")
            name_item = QTableWidgetItem(file_name)
            self.table.setItem(row, 1, name_item)

            # R2 ключ
            r2_key = file_data.get("r2_key", "")
            key_item = QTableWidgetItem(r2_key)
            key_item.setToolTip(r2_key)
            self.table.setItem(row, 2, key_item)

            # Размер файла
            file_size = file_data.get("file_size", 0)
            size_str = self._format_size(file_size)
            size_item = QTableWidgetItem(size_str)
            size_item.setData(Qt.UserRole, file_size)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, size_item)

            # MIME тип
            mime_type = file_data.get("mime_type", "")
            mime_item = QTableWidgetItem(mime_type)
            self.table.setItem(row, 4, mime_item)

            # Дата создания
            created_at = file_data.get("created_at", "")
            created_str = self._format_datetime(created_at)
            created_item = QTableWidgetItem(created_str)
            created_item.setData(Qt.UserRole, created_at)
            self.table.setItem(row, 5, created_item)

        # Установить заголовок с количеством
        self.setWindowTitle(f"Файлы узла: {self.node.name} ({len(self.files)})")

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
            # Парсим ISO формат
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return dt_str
