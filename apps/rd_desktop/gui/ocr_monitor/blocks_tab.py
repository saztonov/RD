"""Вкладка отображения блоков"""
from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class BlocksTab(QWidget):
    """Вкладка со списком всех блоков"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._blocks_data = []
        self._setup_ui()

    def _setup_ui(self):
        """Настройка UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        splitter = QSplitter(Qt.Horizontal)

        # Левая часть: дерево блоков
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Статистика
        self._stats_label = QLabel("Блоки: 0")
        self._stats_label.setStyleSheet("font-weight: bold; padding: 5px;")
        left_layout.addWidget(self._stats_label)

        # Дерево блоков
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Блок", "Тип", "Категория", "Статус"])
        self._tree.setAlternatingRowColors(True)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)

        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        left_layout.addWidget(self._tree)
        splitter.addWidget(left_widget)

        # Правая часть: preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._preview_label = QLabel("Выберите блок для просмотра")
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setStyleSheet(
            "background-color: #f0f0f0; border: 1px solid #ccc; padding: 20px;"
        )
        self._preview_label.setMinimumSize(200, 200)
        right_layout.addWidget(self._preview_label)

        # Информация о блоке
        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        self._info_label.setStyleSheet("padding: 10px;")
        right_layout.addWidget(self._info_label)

        splitter.addWidget(right_widget)
        splitter.setSizes([500, 300])

        layout.addWidget(splitter)

    def update_data(self, blocks: List[dict], phase_data: dict):
        """Обновить данные блоков"""
        self._blocks_data = blocks
        self._phase_data = phase_data

        # Статистика
        summary = phase_data.get("blocks_summary", {})
        total = summary.get("total", len(blocks))
        text_count = summary.get("text", 0)
        image_count = summary.get("image", 0)
        stamp_count = summary.get("stamp", 0)

        stats_text = f"Блоки: {total} (TEXT: {text_count}, IMAGE: {image_count}, STAMP: {stamp_count})"
        self._stats_label.setText(stats_text)

        # Собираем статусы блоков из phase_data
        block_statuses = self._get_block_statuses(phase_data)

        # Обновляем дерево
        self._tree.clear()

        # Группируем по страницам
        blocks_by_page = defaultdict(list)
        for block in blocks:
            page_idx = block.get("page_index", 0)
            blocks_by_page[page_idx].append(block)

        for page_idx in sorted(blocks_by_page.keys()):
            page_item = QTreeWidgetItem([f"Страница {page_idx + 1}", "", "", ""])
            page_item.setExpanded(True)

            for block in blocks_by_page[page_idx]:
                block_id = block.get("id", "")
                block_type = block.get("block_type", "")
                category = block.get("category_code", "") or ""
                status = block_statuses.get(block_id, "pending")

                status_icon = {
                    "pending": "...",
                    "processing": "...",
                    "completed": "+",
                    "error": "x",
                }.get(status, "?")

                type_display = block_type.upper() if block_type else ""

                block_item = QTreeWidgetItem([
                    block_id[:13] if block_id else "",
                    type_display,
                    category,
                    status_icon,
                ])

                # Цвет по статусу
                if status == "completed":
                    block_item.setForeground(3, Qt.darkGreen)
                elif status == "processing":
                    block_item.setForeground(3, Qt.blue)
                elif status == "error":
                    block_item.setForeground(3, Qt.red)

                # Сохраняем данные блока
                block_item.setData(0, Qt.UserRole, block)

                page_item.addChild(block_item)

            self._tree.addTopLevelItem(page_item)

    def _get_block_statuses(self, phase_data: dict) -> dict:
        """Получить статусы блоков из phase_data"""
        statuses = {}

        # Strips
        pass2_strips = phase_data.get("pass2_strips", {})
        for strip in pass2_strips.get("strips", []):
            strip_status = strip.get("status", "pending")
            for block_id in strip.get("block_ids", []):
                statuses[block_id] = strip_status

        # Images
        pass2_images = phase_data.get("pass2_images", {})
        for img in pass2_images.get("images", []):
            block_id = img.get("block_id")
            if block_id:
                statuses[block_id] = img.get("status", "pending")

        return statuses

    def _on_selection_changed(self):
        """Обработка выбора блока"""
        items = self._tree.selectedItems()
        if not items:
            return

        item = items[0]
        block_data = item.data(0, Qt.UserRole)
        if not block_data:
            return

        # Показываем информацию о блоке
        block_id = block_data.get("id", "")
        block_type = block_data.get("block_type", "")
        page_idx = block_data.get("page_index", 0)
        coords = block_data.get("coords_norm", [])
        ocr_text = block_data.get("ocr_text", "")

        info_parts = [
            f"ID: {block_id}",
            f"Тип: {block_type}",
            f"Страница: {page_idx + 1}",
        ]

        if coords:
            info_parts.append(f"Координаты: {coords}")

        if ocr_text:
            preview = ocr_text[:200] + "..." if len(ocr_text) > 200 else ocr_text
            info_parts.append(f"\nТекст OCR:\n{preview}")

        self._info_label.setText("\n".join(info_parts))
