"""Вкладка отображения групп и strips"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class GroupsTab(QWidget):
    """Вкладка с группировкой блоков (strips и images)"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._phase_data = {}
        self._text_blocks = []
        self._batches = []
        self._batch_by_strip_id = {}
        self._r2_base_url = None
        self._text_block_loaded = False
        self._last_fetch_attempt = 0.0
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

        # Text blocks section
        self._text_blocks_group = QGroupBox("Текстовые блоки")
        text_blocks_layout = QVBoxLayout(self._text_blocks_group)

        self._text_blocks_stats = QLabel("Текстовые блоки: 0")
        self._text_blocks_stats.setStyleSheet("font-weight: bold;")
        text_blocks_layout.addWidget(self._text_blocks_stats)

        self._text_blocks_list = QListWidget()
        self._text_blocks_list.itemSelectionChanged.connect(
            self._on_text_block_selected
        )
        text_blocks_layout.addWidget(self._text_blocks_list)

        left_layout.addWidget(self._text_blocks_group)

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
        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setPlaceholderText("Текст OCR будет отображен здесь")
        self._preview_text.setStyleSheet(
            "background-color: #e0e0e0; border: 1px solid #ccc; padding: 10px;"
        )
        self._preview_text.setMinimumSize(200, 200)
        right_layout.addWidget(self._preview_text, 1)

        splitter.addWidget(right_widget)
        splitter.setSizes([400, 400])

        layout.addWidget(splitter)

    def update_data(self, phase_data: dict, r2_base_url: Optional[str] = None):
        """Обновить данные групп"""
        self._phase_data = phase_data
        if r2_base_url and r2_base_url != self._r2_base_url:
            self._r2_base_url = r2_base_url
            self._text_block_loaded = False
            self._text_blocks = []
            self._batches = []
            self._batch_by_strip_id = {}
            self._last_fetch_attempt = 0.0

        if self._r2_base_url and not self._text_block_loaded:
            self._try_load_text_block_data()

        # Логирование входных данных
        logger.info(
            f"[GroupsTab.update_data] phase_data: {bool(phase_data)}, "
            f"keys={list(phase_data.keys()) if phase_data else 'None'}"
        )

        # Обновляем strips
        pass2_strips = phase_data.get("pass2_strips", {})
        strips = pass2_strips.get("strips", [])
        strips_total = pass2_strips.get("total", 0)
        strips_processed = pass2_strips.get("processed", 0)

        if not strips and self._batches:
            strips = [
                {
                    "strip_id": batch.get("strip_id", ""),
                    "block_ids": batch.get("block_ids", []),
                    "status": "completed",
                }
                for batch in self._batches
                if isinstance(batch, dict)
            ]
            strips_total = len(strips)
            strips_processed = len(strips)

        logger.info(
            f"[GroupsTab] pass2_strips: total={strips_total}, processed={strips_processed}, "
            f"strips_list_len={len(strips) if strips else 0}"
        )

        if strips:
            for i, strip in enumerate(strips[:3]):
                logger.debug(
                    f"[GroupsTab] Strip {i}: id={strip.get('strip_id', 'N/A')}, "
                    f"blocks={len(strip.get('block_ids', []))}, status={strip.get('status')}"
                )

        self._strips_stats.setText(f"Strips: {strips_processed}/{strips_total}")
        self._update_strips_list(strips, self._batch_by_strip_id)

        self._text_blocks_stats.setText(f"Текстовые блоки: {len(self._text_blocks)}")
        self._update_text_blocks_list(self._text_blocks)

        # Обновляем images
        pass2_images = phase_data.get("pass2_images", {})
        images = pass2_images.get("images", [])
        images_total = pass2_images.get("total", 0)
        images_processed = pass2_images.get("processed", 0)

        logger.info(
            f"[GroupsTab] pass2_images: total={images_total}, processed={images_processed}, "
            f"images_list_len={len(images) if images else 0}"
        )

        if images:
            for i, img in enumerate(images[:3]):
                logger.debug(
                    f"[GroupsTab] Image {i}: block_id={img.get('block_id', 'N/A')[:13] if img.get('block_id') else 'N/A'}, "
                    f"status={img.get('status')}, is_stamp={img.get('is_stamp')}"
                )

        self._images_stats.setText(f"Images: {images_processed}/{images_total}")
        self._update_images_list(images)

    def _try_load_text_block_data(self) -> None:
        now = time.monotonic()
        if now - self._last_fetch_attempt < 5:
            return
        self._last_fetch_attempt = now

        blocks_url = f"{self._r2_base_url}/text_block/blocks.json"
        batches_url = f"{self._r2_base_url}/text_block/batches.json"

        blocks_data = self._fetch_json(blocks_url)
        batches_data = self._fetch_json(batches_url)

        if blocks_data is None and batches_data is None:
            return

        if blocks_data is not None:
            self._text_blocks = self._extract_list(blocks_data, "blocks")

        if batches_data is not None:
            self._batches = self._extract_list(batches_data, "batches")
            self._batch_by_strip_id = {
                b.get("strip_id"): b
                for b in self._batches
                if isinstance(b, dict) and b.get("strip_id")
            }

        self._text_block_loaded = blocks_data is not None and batches_data is not None

    def _fetch_json(self, url: str):
        try:
            resp = httpx.get(url, timeout=10.0)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("Failed to fetch %s: %s", url, exc)
            return None

    @staticmethod
    def _extract_list(payload, key: str) -> list:
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            items = payload.get(key)
            if isinstance(items, list):
                return items
        return []

    def _update_strips_list(self, strips: list, batch_by_strip_id: dict):
        """Обновить список strips"""
        self._strips_list.clear()

        for strip in strips:
            strip_id = strip.get("strip_id", "")
            block_ids = strip.get("block_ids", [])
            status = strip.get("status", "pending")
            batch = batch_by_strip_id.get(strip_id)

            status_icon = self._get_status_icon(status)
            text = f"{status_icon} {strip_id} ({len(block_ids)} блоков)"

            item = QListWidgetItem(text)
            item_data = dict(strip)
            if batch:
                item_data["batch"] = batch
            item.setData(Qt.UserRole, item_data)

            # Цвет по статусу
            if status == "completed":
                item.setForeground(Qt.darkGreen)
            elif status == "processing":
                item.setForeground(Qt.blue)
            elif status == "error":
                item.setForeground(Qt.red)

            self._strips_list.addItem(item)

    def _update_text_blocks_list(self, blocks: list):
        """Обновить список текстовых блоков"""
        self._text_blocks_list.clear()

        for block in blocks:
            block_id = block.get("id") or block.get("block_id", "")
            page_idx = block.get("page_index", 0)
            strip_id = block.get("strip_id")

            text = f"{block_id[:13]} (стр. {page_idx + 1})"
            if strip_id:
                text = f"{text} [{strip_id}]"

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, block)
            self._text_blocks_list.addItem(item)

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

    def _on_text_block_selected(self):
        """Обработка выбора текстового блока"""
        items = self._text_blocks_list.selectedItems()
        if not items:
            return

        block_data = items[0].data(Qt.UserRole)
        if not block_data:
            return

        block_id = block_data.get("id") or block_data.get("block_id", "")
        page_idx = block_data.get("page_index", 0)
        strip_id = block_data.get("strip_id")
        coords = block_data.get("coords_norm") or []
        ocr_text = block_data.get("ocr_text", "")

        details = [
            f"Block ID: {block_id}",
            f"Страница: {page_idx + 1}",
        ]
        if strip_id:
            details.append(f"Strip: {strip_id}")
        if coords:
            details.append(f"Координаты: {coords}")

        self._details_label.setText("\n".join(details))
        self._preview_text.setPlainText(ocr_text or "OCR текст недоступен")

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

        batch = strip_data.get("batch")
        if batch:
            preview_lines = []
            for block in batch.get("blocks", []):
                block_id = block.get("block_id", "")
                text = block.get("ocr_text", "")
                if text:
                    preview_lines.append(f"{block_id}\n{text}")
                else:
                    preview_lines.append(f"{block_id}\n[empty]")
            self._preview_text.setPlainText("\n\n".join(preview_lines))
        else:
            self._preview_text.setPlainText("Данные batch пока недоступны.")

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
        self._preview_text.setPlainText("Для IMAGE блоков текст не отображается.")
