"""Вкладка отображения результатов OCR"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ResultsTab(QWidget):
    """Вкладка с результатами OCR по блокам"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._blocks_data = []
        self._setup_ui()

    def _setup_ui(self):
        """Настройка UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        splitter = QSplitter(Qt.Horizontal)

        # Левая часть: список блоков с результатами
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._stats_label = QLabel("Результаты: 0/0")
        self._stats_label.setStyleSheet("font-weight: bold; padding: 5px;")
        left_layout.addWidget(self._stats_label)

        self._results_list = QListWidget()
        self._results_list.itemSelectionChanged.connect(self._on_result_selected)
        left_layout.addWidget(self._results_list)

        splitter.addWidget(left_widget)

        # Правая часть: текст результата
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._block_info_label = QLabel("Выберите блок")
        self._block_info_label.setStyleSheet("font-weight: bold; padding: 5px;")
        right_layout.addWidget(self._block_info_label)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setPlaceholderText("Результат OCR будет отображен здесь")
        right_layout.addWidget(self._result_text)

        splitter.addWidget(right_widget)
        splitter.setSizes([350, 550])

        layout.addWidget(splitter)

    def update_data(self, blocks: List[dict], phase_data: dict):
        """Обновить данные результатов"""
        self._blocks_data = blocks

        # Подсчет блоков с результатами
        blocks_with_results = [b for b in blocks if b.get("ocr_text")]
        total_blocks = len(blocks)
        completed_blocks = len(blocks_with_results)

        self._stats_label.setText(f"Результаты: {completed_blocks}/{total_blocks}")

        # Обновляем список
        self._results_list.clear()

        for block in blocks:
            block_id = block.get("id", "")
            block_type = block.get("block_type", "")
            category = block.get("category_code", "")
            ocr_text = block.get("ocr_text", "")

            has_result = bool(ocr_text)

            # Формируем текст элемента
            type_label = block_type.upper() if block_type else ""
            if category:
                type_label = f"{type_label}/{category}"

            status_icon = "[OK]" if has_result else "[...]"
            text = f"{status_icon} {block_id[:13]} ({type_label})"

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, block)

            if has_result:
                item.setForeground(Qt.darkGreen)
            else:
                item.setForeground(Qt.gray)

            self._results_list.addItem(item)

    def _on_result_selected(self):
        """Обработка выбора блока"""
        items = self._results_list.selectedItems()
        if not items:
            return

        block_data = items[0].data(Qt.UserRole)
        if not block_data:
            return

        block_id = block_data.get("id", "")
        block_type = block_data.get("block_type", "")
        category = block_data.get("category_code", "")
        page_idx = block_data.get("page_index", 0)
        ocr_text = block_data.get("ocr_text", "")

        # Заголовок
        type_label = block_type.upper() if block_type else ""
        if category:
            type_label = f"{type_label} ({category})"

        self._block_info_label.setText(f"{block_id} - {type_label} - Стр. {page_idx + 1}")

        # Результат
        if ocr_text:
            # Форматируем в зависимости от типа
            if block_type == "image" or category == "stamp":
                # Пытаемся форматировать как JSON
                try:
                    import json
                    parsed = json.loads(ocr_text)
                    formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
                    self._result_text.setPlainText(formatted)
                except (json.JSONDecodeError, TypeError):
                    self._result_text.setPlainText(ocr_text)
            else:
                self._result_text.setPlainText(ocr_text)
        else:
            self._result_text.setPlainText("Результат ещё не получен...")
