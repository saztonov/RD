"""Главное окно мониторинга процесса OCR"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from .blocks_tab import BlocksTab
from .documents_tab import DocumentsTab
from .groups_tab import GroupsTab
from .results_tab import ResultsTab

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


def _safe_len(obj) -> int:
    """Безопасно получить длину объекта"""
    if obj is None:
        return 0
    try:
        return len(obj)
    except TypeError:
        return 0


class OCRMonitorDialog(QDialog):
    """Окно мониторинга процесса OCR"""

    progress_updated = Signal(dict)

    def __init__(self, job_id: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.job_id = job_id
        self._client = None
        self._last_status = None
        self._progress_data = {}

        self.setWindowTitle(f"Мониторинг OCR - {job_id[:8]}...")
        self.setMinimumSize(900, 700)
        self.resize(1000, 750)

        self._setup_ui()
        self._setup_polling()

        # Первоначальная загрузка
        QTimer.singleShot(100, self._fetch_progress)

    def _setup_ui(self):
        """Настройка UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Заголовок с прогрессом
        header_layout = QVBoxLayout()

        # Статус
        self._status_label = QLabel("Загрузка...")
        self._status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(self._status_label)

        # Прогресс-бар
        progress_layout = QHBoxLayout()
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        progress_layout.addWidget(self._progress_bar)

        self._progress_text = QLabel("0%")
        self._progress_text.setMinimumWidth(50)
        progress_layout.addWidget(self._progress_text)

        header_layout.addLayout(progress_layout)
        layout.addLayout(header_layout)

        # Вкладки
        self._tabs = QTabWidget()

        self._blocks_tab = BlocksTab()
        self._tabs.addTab(self._blocks_tab, "Блоки")

        self._groups_tab = GroupsTab()
        self._tabs.addTab(self._groups_tab, "Группы")

        self._results_tab = ResultsTab()
        self._tabs.addTab(self._results_tab, "Результаты")

        self._documents_tab = DocumentsTab()
        self._tabs.addTab(self._documents_tab, "Документы")

        layout.addWidget(self._tabs, 1)

        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self._open_folder_btn = QPushButton("Открыть папку")
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.clicked.connect(self._open_folder)
        buttons_layout.addWidget(self._open_folder_btn)

        self._close_btn = QPushButton("Закрыть")
        self._close_btn.clicked.connect(self.close)
        buttons_layout.addWidget(self._close_btn)

        layout.addLayout(buttons_layout)

    def _setup_polling(self):
        """Настройка polling для обновления прогресса"""
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._fetch_progress)
        self._poll_timer.start(3000)  # Каждые 3 секунды

    def _get_client(self):
        """Получить клиент RemoteOCR"""
        if self._client is None:
            try:
                from apps.rd_desktop.ocr_client import RemoteOCRClient

                self._client = RemoteOCRClient()
            except Exception as e:
                logger.error(f"Ошибка создания клиента: {e}")
        return self._client

    def _fetch_progress(self):
        """Получить прогресс задачи"""
        client = self._get_client()
        if not client:
            logger.warning(f"[OCRMonitor] Клиент не доступен для job_id={self.job_id[:8]}")
            return

        try:
            progress_data = client.get_job_progress(self.job_id)
            self._progress_data = progress_data

            # Детальное логирование полученных данных
            status = progress_data.get("status", "unknown")
            progress = progress_data.get("progress", 0)
            blocks = progress_data.get("blocks") or []
            phase_data = progress_data.get("phase_data") or {}

            logger.info(
                f"[OCRMonitor] job_id={self.job_id[:8]}: "
                f"status={status}, progress={progress:.1%}, "
                f"blocks_count={_safe_len(blocks)}, "
                f"phase_data_keys={list(phase_data.keys()) if phase_data else 'None'}"
            )

            # Логируем детали phase_data
            if phase_data:
                current_phase = phase_data.get("current_phase", "unknown")
                blocks_summary = phase_data.get("blocks_summary", {})
                pass2_strips = phase_data.get("pass2_strips", {})
                pass2_images = phase_data.get("pass2_images", {})

                logger.debug(
                    f"[OCRMonitor] phase_data: current_phase={current_phase}, "
                    f"blocks_summary={blocks_summary}, "
                    f"strips_count={_safe_len(pass2_strips.get('strips'))}, "
                    f"images_count={_safe_len(pass2_images.get('images'))}"
                )

            self._update_ui(progress_data)

            # Остановить polling если задача завершена
            if status in ("done", "error"):
                self._poll_timer.stop()
                logger.info(f"[OCRMonitor] Polling остановлен: status={status}")
                if status == "done":
                    self._open_folder_btn.setEnabled(True)

        except Exception as e:
            logger.warning(f"[OCRMonitor] Ошибка получения прогресса: {e}", exc_info=True)

    def _update_ui(self, data: dict):
        """Обновить UI по данным прогресса"""
        status = data.get("status", "")
        progress = data.get("progress", 0) or 0
        status_message = data.get("status_message", "")
        phase_data = data.get("phase_data") or {}
        blocks = data.get("blocks") or []
        error_message = data.get("error_message")

        logger.debug(
            f"[OCRMonitor._update_ui] Обновление UI: blocks={len(blocks)}, "
            f"phase_data={bool(phase_data)}, status={status}"
        )

        # Обновляем статус
        status_text = self._get_status_text(status, status_message, error_message)
        self._status_label.setText(status_text)

        # Обновляем прогресс
        progress_pct = int(progress * 100)
        self._progress_bar.setValue(progress_pct)
        self._progress_text.setText(f"{progress_pct}%")

        # Стиль прогресс-бара по статусу
        if status == "done":
            self._progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #4CAF50; }")
        elif status == "error":
            self._progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #f44336; }")
        else:
            self._progress_bar.setStyleSheet("")

        # Обновляем вкладки
        self._blocks_tab.update_data(blocks, phase_data)
        self._groups_tab.update_data(phase_data)
        self._results_tab.update_data(blocks, phase_data)

        if status == "done":
            r2_base_url = data.get("r2_base_url")
            self._documents_tab.update_data(r2_base_url, self.job_id)

    def _get_status_text(self, status: str, message: str, error: str) -> str:
        """Получить текст статуса"""
        status_icons = {
            "queued": "В очереди",
            "processing": "Обработка",
            "done": "Завершено",
            "error": "Ошибка",
        }
        base = status_icons.get(status, status)

        if error:
            return f"{base}: {error}"
        if message:
            return f"{base}: {message}"
        return base

    def _open_folder(self):
        """Открыть папку с результатами"""
        import os
        import subprocess
        from pathlib import Path

        # Получаем путь к папке результатов
        parent = self.parent()
        if parent and hasattr(parent, "main_window"):
            pdf_path = getattr(parent.main_window, "_current_pdf_path", None)
            if pdf_path:
                folder = Path(pdf_path).parent
                if folder.exists():
                    if os.name == "nt":
                        subprocess.run(["explorer", str(folder)])
                    else:
                        subprocess.run(["xdg-open", str(folder)])

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        self._poll_timer.stop()
        super().closeEvent(event)
