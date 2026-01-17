"""Вкладка отображения итоговых документов"""
from __future__ import annotations

import webbrowser
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DocumentsTab(QWidget):
    """Вкладка с итоговыми документами"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._r2_base_url = None
        self._job_id = None
        self._setup_ui()

    def _setup_ui(self):
        """Настройка UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Статус
        self._status_label = QLabel("Ожидание завершения обработки...")
        self._status_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        self._status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status_label)

        # Группа документов
        self._docs_group = QGroupBox("Сгенерированные документы")
        docs_layout = QVBoxLayout(self._docs_group)

        self._docs_list = QListWidget()
        self._docs_list.setMinimumHeight(200)
        docs_layout.addWidget(self._docs_list)

        # Кнопки действий
        buttons_layout = QHBoxLayout()

        self._open_btn = QPushButton("Открыть в браузере")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_selected)
        buttons_layout.addWidget(self._open_btn)

        self._copy_url_btn = QPushButton("Копировать URL")
        self._copy_url_btn.setEnabled(False)
        self._copy_url_btn.clicked.connect(self._copy_url)
        buttons_layout.addWidget(self._copy_url_btn)

        buttons_layout.addStretch()
        docs_layout.addLayout(buttons_layout)

        layout.addWidget(self._docs_group)

        # Описание файлов
        self._description = QLabel(
            "После завершения обработки здесь появятся ссылки на:\n\n"
            "- annotation.json - блоки с результатами OCR\n"
            "- ocr.html - HTML представление результатов\n"
            "- result.json - полные данные с метаинформацией\n"
            "- document.md - Markdown документ для LLM"
        )
        self._description.setStyleSheet("color: #666; padding: 10px;")
        self._description.setWordWrap(True)
        layout.addWidget(self._description)

        layout.addStretch()

        # Подключаем события
        self._docs_list.itemSelectionChanged.connect(self._on_selection_changed)

    def update_data(self, r2_base_url: Optional[str], job_id: str):
        """Обновить данные документов"""
        self._r2_base_url = r2_base_url
        self._job_id = job_id

        if not r2_base_url:
            self._status_label.setText("Ожидание завершения обработки...")
            self._docs_list.clear()
            self._open_btn.setEnabled(False)
            self._copy_url_btn.setEnabled(False)
            return

        self._status_label.setText("Обработка завершена!")
        self._status_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; padding: 10px; color: #4CAF50;"
        )

        # Список документов
        documents = [
            ("annotation.json", "Блоки с результатами OCR"),
            ("ocr.html", "HTML представление"),
            ("result.json", "Полные данные"),
            ("document.md", "Markdown документ"),
        ]

        self._docs_list.clear()
        for filename, description in documents:
            url = f"{r2_base_url}/{filename}"
            item = QListWidgetItem(f"{filename} - {description}")
            item.setData(Qt.UserRole, url)
            self._docs_list.addItem(item)

    def _on_selection_changed(self):
        """Обработка выбора документа"""
        items = self._docs_list.selectedItems()
        has_selection = bool(items)
        self._open_btn.setEnabled(has_selection)
        self._copy_url_btn.setEnabled(has_selection)

    def _open_selected(self):
        """Открыть выбранный документ в браузере"""
        items = self._docs_list.selectedItems()
        if not items:
            return

        url = items[0].data(Qt.UserRole)
        if url:
            webbrowser.open(url)

    def _copy_url(self):
        """Копировать URL в буфер обмена"""
        items = self._docs_list.selectedItems()
        if not items:
            return

        url = items[0].data(Qt.UserRole)
        if url:
            from PySide6.QtWidgets import QApplication

            clipboard = QApplication.clipboard()
            clipboard.setText(url)
