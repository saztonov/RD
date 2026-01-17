"""Вкладка отображения групп и strips"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class GroupsTab(QWidget):
    """Вкладка с группировкой блоков (strips и images)"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._phase_data = {}
        self._setup_ui()

    def _setup_ui(self):
        """Настройка UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        splitter = QSplitter(Qt.Horizontal)

        # Левая часть: списки групп
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Strips секция
        self._strips_group = QGroupBox("Strips (TEXT блоки)")
        strips_layout = QVBoxLayout(self._strips_group)

        self._strips_stats = QLabel("Strips: 0")
        self._strips_stats.setStyleSheet("font-weight: bold;")
        strips_layout.addWidget(self._strips_stats)

        self._strips_list = QListWidget()
        self._strips_list.itemSelectionChanged.connect(self._on_strip_selected)
        strips_layout.addWidget(self._strips_list)

        left_layout.addWidget(self._strips_group)

        # Images секция
        self._images_group = QGroupBox("IMAGE блоки")
        images_layout = QVBoxLayout(self._images_group)

        self._images_stats = QLabel("Images: 0")
        self._images_stats.setStyleSheet("font-weight: bold;")
        images_layout.addWidget(self._images_stats)

        self._images_list = QListWidget()
        self._images_list.itemSelectionChanged.connect(self._on_image_selected)
        images_layout.addWidget(self._images_list)

        left_layout.addWidget(self._images_group)

        splitter.addWidget(left_widget)

        # Правая часть: детали и preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._details_label = QLabel("Выберите группу для просмотра")
        self._details_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._details_label.setWordWrap(True)
        self._details_label.setStyleSheet(
            "background-color: #f5f5f5; border: 1px solid #ddd; padding: 15px;"
        )
        self._details_label.setMinimumHeight(150)
        right_layout.addWidget(self._details_label)

        # Preview area
        self._preview_label = QLabel("Preview недоступен")
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setStyleSheet(
            "background-color: #e0e0e0; border: 1px solid #ccc; padding: 20px;"
        )
        self._preview_label.setMinimumSize(200, 200)
        right_layout.addWidget(self._preview_label, 1)

        splitter.addWidget(right_widget)
        splitter.setSizes([400, 400])

        layout.addWidget(splitter)

    def update_data(self, phase_data: dict):
        """Обновить данные групп"""
        self._phase_data = phase_data

        # Обновляем strips
        pass2_strips = phase_data.get("pass2_strips", {})
        strips = pass2_strips.get("strips", [])
        strips_total = pass2_strips.get("total", 0)
        strips_processed = pass2_strips.get("processed", 0)

        self._strips_stats.setText(f"Strips: {strips_processed}/{strips_total}")
        self._update_strips_list(strips)

        # Обновляем images
        pass2_images = phase_data.get("pass2_images", {})
        images = pass2_images.get("images", [])
        images_total = pass2_images.get("total", 0)
        images_processed = pass2_images.get("processed", 0)

        self._images_stats.setText(f"Images: {images_processed}/{images_total}")
        self._update_images_list(images)

    def _update_strips_list(self, strips: list):
        """Обновить список strips"""
        self._strips_list.clear()

        for strip in strips:
            strip_id = strip.get("strip_id", "")
            block_ids = strip.get("block_ids", [])
            status = strip.get("status", "pending")

            status_icon = self._get_status_icon(status)
            text = f"{status_icon} {strip_id} ({len(block_ids)} блоков)"

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, strip)

            # Цвет по статусу
            if status == "completed":
                item.setForeground(Qt.darkGreen)
            elif status == "processing":
                item.setForeground(Qt.blue)
            elif status == "error":
                item.setForeground(Qt.red)

            self._strips_list.addItem(item)

    def _update_images_list(self, images: list):
        """Обновить список images"""
        self._images_list.clear()

        for img in images:
            block_id = img.get("block_id", "")
            status = img.get("status", "pending")
            is_stamp = img.get("is_stamp", False)

            status_icon = self._get_status_icon(status)
            type_label = "STAMP" if is_stamp else "IMAGE"
            text = f"{status_icon} [{type_label}] {block_id[:13]}"

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, img)

            # Цвет по статусу
            if status == "completed":
                item.setForeground(Qt.darkGreen)
            elif status == "processing":
                item.setForeground(Qt.blue)
            elif status == "error":
                item.setForeground(Qt.red)

            self._images_list.addItem(item)

    def _get_status_icon(self, status: str) -> str:
        """Получить иконку статуса"""
        return {
            "pending": "[...]",
            "processing": "[>>>]",
            "completed": "[OK]",
            "error": "[ERR]",
        }.get(status, "[?]")

    def _on_strip_selected(self):
        """Обработка выбора strip"""
        items = self._strips_list.selectedItems()
        if not items:
            return

        strip_data = items[0].data(Qt.UserRole)
        if not strip_data:
            return

        strip_id = strip_data.get("strip_id", "")
        block_ids = strip_data.get("block_ids", [])
        status = strip_data.get("status", "")

        details = [
            f"Strip ID: {strip_id}",
            f"Статус: {status}",
            f"Блоков: {len(block_ids)}",
            "",
            "Блоки в strip:",
        ]

        for bid in block_ids:
            details.append(f"  - {bid}")

        self._details_label.setText("\n".join(details))

    def _on_image_selected(self):
        """Обработка выбора image"""
        items = self._images_list.selectedItems()
        if not items:
            return

        img_data = items[0].data(Qt.UserRole)
        if not img_data:
            return

        block_id = img_data.get("block_id", "")
        status = img_data.get("status", "")
        is_stamp = img_data.get("is_stamp", False)

        details = [
            f"Block ID: {block_id}",
            f"Тип: {'STAMP' if is_stamp else 'IMAGE'}",
            f"Статус: {status}",
        ]

        self._details_label.setText("\n".join(details))
