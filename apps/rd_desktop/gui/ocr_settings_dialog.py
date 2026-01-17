"""Диалог настроек OCR сервера"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from apps.rd_desktop.tree_client import TreeClient, _get_tree_client

logger = logging.getLogger(__name__)


@dataclass
class OCRSettings:
    """Настройки OCR сервера"""

    # Celery Worker
    max_concurrent_jobs: int = 4
    worker_prefetch: int = 1
    worker_max_tasks: int = 100
    task_soft_timeout: int = 1800
    task_hard_timeout: int = 2100
    task_max_retries: int = 3
    task_retry_delay: int = 60

    # OCR Threading
    max_global_ocr_requests: int = 8
    ocr_threads_per_job: int = 2
    ocr_request_timeout: int = 120

    # Datalab API
    datalab_max_rpm: int = 180
    datalab_max_concurrent: int = 5
    datalab_poll_interval: int = 3
    datalab_poll_max_attempts: int = 90
    datalab_max_retries: int = 3

    # Двухпроходный алгоритм
    use_two_pass_ocr: bool = True
    crop_png_compress: int = 6
    max_ocr_batch_size: int = 5
    pdf_render_dpi: int = 150
    max_strip_height: int = 9000
    block_separator_height: int = 100

    # Очередь
    poll_interval: float = 10.0
    poll_max_interval: float = 60.0
    max_queue_size: int = 100
    default_task_priority: int = 5

    # Rate Limiting (распределённый на Redis)
    rate_limit_datalab_rpm: int = 180
    rate_limit_datalab_concurrent: int = 5
    rate_limit_openrouter_rpm: int = 60
    rate_limit_openrouter_concurrent: int = 8
    rate_limit_client_rpm: int = 30
    rate_limit_client_concurrent: int = 4
    rate_limit_backoff_base: float = 5.0
    rate_limit_backoff_max: float = 60.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "OCRSettings":
        # Фильтруем только известные поля
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class OCRSettingsDialog(QDialog):
    """Диалог настроек OCR сервера"""

    SETTINGS_KEY = "ocr_server_settings"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = TreeClient()
        self.settings = OCRSettings()
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        self.setWindowTitle("⚙️ Настройки OCR сервера")
        self.setMinimumWidth(500)
        self.setMinimumHeight(600)

        layout = QVBoxLayout(self)

        # Вкладки
        tabs = QTabWidget()

        # Вкладка: Celery Worker
        tabs.addTab(self._create_worker_tab(), "🔧 Worker")

        # Вкладка: OCR Threading
        tabs.addTab(self._create_ocr_tab(), "🧵 OCR потоки")

        # Вкладка: Алгоритм
        tabs.addTab(self._create_algorithm_tab(), "📐 Алгоритм")

        # Вкладка: Очередь
        tabs.addTab(self._create_queue_tab(), "📋 Очередь")

        # Вкладка: Rate Limit
        tabs.addTab(self._create_rate_limit_tab(), "⏱️ Rate Limit")

        layout.addWidget(tabs)

        # Кнопки
        btns = QHBoxLayout()

        reset_btn = QPushButton("🔄 Сбросить")
        reset_btn.clicked.connect(self._reset_defaults)
        btns.addWidget(reset_btn)

        export_btn = QPushButton("📤 Экспорт всех настроек")
        export_btn.clicked.connect(self._export_all_settings)
        export_btn.setToolTip("Выгрузить все настройки из БД в JSON файл")
        btns.addWidget(export_btn)

        btns.addStretch()

        save_btn = QPushButton("💾 Сохранить")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save_settings)
        btns.addWidget(save_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)

        layout.addLayout(btns)

    def _create_worker_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Группа: Параллельность
        group1 = QGroupBox("Параллельность")
        form1 = QFormLayout(group1)

        self.max_concurrent_jobs_spin = QSpinBox()
        self.max_concurrent_jobs_spin.setRange(1, 16)
        self.max_concurrent_jobs_spin.setToolTip("Количество параллельных Celery задач")
        form1.addRow("Параллельных задач:", self.max_concurrent_jobs_spin)

        self.worker_prefetch_spin = QSpinBox()
        self.worker_prefetch_spin.setRange(1, 10)
        self.worker_prefetch_spin.setToolTip(
            "Сколько задач брать заранее (1 = по одной)"
        )
        form1.addRow("Prefetch:", self.worker_prefetch_spin)

        self.worker_max_tasks_spin = QSpinBox()
        self.worker_max_tasks_spin.setRange(10, 1000)
        self.worker_max_tasks_spin.setToolTip(
            "Перезапуск воркера после N задач (защита от утечек)"
        )
        form1.addRow("Макс. задач до рестарта:", self.worker_max_tasks_spin)

        layout.addWidget(group1)

        # Группа: Таймауты
        group2 = QGroupBox("Таймауты и повторы")
        form2 = QFormLayout(group2)

        self.task_soft_timeout_spin = QSpinBox()
        self.task_soft_timeout_spin.setRange(60, 7200)
        self.task_soft_timeout_spin.setSuffix(" сек")
        self.task_soft_timeout_spin.setToolTip("Soft таймаут задачи (предупреждение)")
        form2.addRow("Soft таймаут:", self.task_soft_timeout_spin)

        self.task_hard_timeout_spin = QSpinBox()
        self.task_hard_timeout_spin.setRange(60, 7200)
        self.task_hard_timeout_spin.setSuffix(" сек")
        self.task_hard_timeout_spin.setToolTip(
            "Hard таймаут задачи (принудительное завершение)"
        )
        form2.addRow("Hard таймаут:", self.task_hard_timeout_spin)

        self.task_max_retries_spin = QSpinBox()
        self.task_max_retries_spin.setRange(0, 10)
        self.task_max_retries_spin.setToolTip("Количество повторов при ошибке")
        form2.addRow("Повторов при ошибке:", self.task_max_retries_spin)

        self.task_retry_delay_spin = QSpinBox()
        self.task_retry_delay_spin.setRange(10, 600)
        self.task_retry_delay_spin.setSuffix(" сек")
        self.task_retry_delay_spin.setToolTip("Задержка между повторами")
        form2.addRow("Задержка повтора:", self.task_retry_delay_spin)

        layout.addWidget(group2)
        layout.addStretch()

        return widget

    def _create_ocr_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Группа: Потоки OCR
        group1 = QGroupBox("Потоки OCR")
        form1 = QFormLayout(group1)

        self.max_global_ocr_spin = QSpinBox()
        self.max_global_ocr_spin.setRange(1, 32)
        self.max_global_ocr_spin.setToolTip(
            "Глобальный лимит параллельных OCR запросов (все задачи)"
        )
        form1.addRow("Глобальный лимит OCR:", self.max_global_ocr_spin)

        self.ocr_threads_per_job_spin = QSpinBox()
        self.ocr_threads_per_job_spin.setRange(1, 8)
        self.ocr_threads_per_job_spin.setToolTip("Потоков OCR внутри одной задачи")
        form1.addRow("Потоков на задачу:", self.ocr_threads_per_job_spin)

        self.ocr_request_timeout_spin = QSpinBox()
        self.ocr_request_timeout_spin.setRange(30, 600)
        self.ocr_request_timeout_spin.setSuffix(" сек")
        self.ocr_request_timeout_spin.setToolTip("Таймаут одного OCR запроса")
        form1.addRow("Таймаут запроса:", self.ocr_request_timeout_spin)

        layout.addWidget(group1)

        # Группа: Datalab API
        group2 = QGroupBox("Datalab API")
        form2 = QFormLayout(group2)

        self.datalab_max_rpm_spin = QSpinBox()
        self.datalab_max_rpm_spin.setRange(10, 1000)
        self.datalab_max_rpm_spin.setToolTip("Максимум запросов в минуту к Datalab")
        form2.addRow("Запросов/минуту:", self.datalab_max_rpm_spin)

        self.datalab_max_concurrent_spin = QSpinBox()
        self.datalab_max_concurrent_spin.setRange(1, 20)
        self.datalab_max_concurrent_spin.setToolTip("Параллельных запросов к Datalab")
        form2.addRow("Параллельных:", self.datalab_max_concurrent_spin)

        self.datalab_poll_interval_spin = QSpinBox()
        self.datalab_poll_interval_spin.setRange(1, 120)
        self.datalab_poll_interval_spin.setSuffix(" сек")
        self.datalab_poll_interval_spin.setToolTip("Интервал между проверками статуса задачи в Datalab")
        form2.addRow("Интервал polling:", self.datalab_poll_interval_spin)

        self.datalab_poll_max_attempts_spin = QSpinBox()
        self.datalab_poll_max_attempts_spin.setRange(1, 500)
        self.datalab_poll_max_attempts_spin.setToolTip("Максимум попыток проверки статуса (90 × 3сек = ~4.5 мин)")
        form2.addRow("Макс. попыток polling:", self.datalab_poll_max_attempts_spin)

        self.datalab_max_retries_spin = QSpinBox()
        self.datalab_max_retries_spin.setRange(0, 10)
        self.datalab_max_retries_spin.setToolTip("Количество повторов при ошибке Datalab API")
        form2.addRow("Повторов при ошибке:", self.datalab_max_retries_spin)

        layout.addWidget(group2)
        layout.addStretch()

        return widget

    def _create_algorithm_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Группа: Двухпроходный алгоритм
        group1 = QGroupBox("Двухпроходный алгоритм")
        form1 = QFormLayout(group1)

        self.use_two_pass_check = QCheckBox("Включить (экономия памяти)")
        self.use_two_pass_check.setToolTip(
            "Сохранять кропы на диск вместо памяти.\n"
            "Снижает потребление RAM с 1-4 GB до 200-400 MB"
        )
        form1.addRow("Двухпроходный:", self.use_two_pass_check)

        self.crop_png_compress_spin = QSpinBox()
        self.crop_png_compress_spin.setRange(0, 9)
        self.crop_png_compress_spin.setToolTip(
            "Сжатие PNG (0=без сжатия, 9=максимальное)"
        )
        form1.addRow("Сжатие PNG:", self.crop_png_compress_spin)

        self.max_ocr_batch_spin = QSpinBox()
        self.max_ocr_batch_spin.setRange(1, 20)
        self.max_ocr_batch_spin.setToolTip("Максимум блоков в одном batch запросе")
        form1.addRow("Batch размер:", self.max_ocr_batch_spin)

        layout.addWidget(group1)

        # Группа: Рендеринг PDF
        group2 = QGroupBox("Рендеринг PDF")
        form2 = QFormLayout(group2)

        self.pdf_render_dpi_spin = QSpinBox()
        self.pdf_render_dpi_spin.setRange(72, 600)
        self.pdf_render_dpi_spin.setSuffix(" DPI")
        self.pdf_render_dpi_spin.setToolTip(
            "DPI рендеринга PDF (влияет на качество и размер)"
        )
        form2.addRow("DPI рендеринга:", self.pdf_render_dpi_spin)

        self.max_strip_height_spin = QSpinBox()
        self.max_strip_height_spin.setRange(1000, 20000)
        self.max_strip_height_spin.setSuffix(" px")
        self.max_strip_height_spin.setToolTip("Максимальная высота полосы (strips)")
        form2.addRow("Макс. высота полосы:", self.max_strip_height_spin)

        self.block_separator_height_spin = QSpinBox()
        self.block_separator_height_spin.setRange(50, 200)
        self.block_separator_height_spin.setSuffix(" px")
        self.block_separator_height_spin.setToolTip(
            "Высота разделителя между блоками в strip.\n"
            "Увеличьте, если маркеры BLOCK не распознаются."
        )
        form2.addRow("Высота разделителя:", self.block_separator_height_spin)

        layout.addWidget(group2)
        layout.addStretch()

        return widget

    def _create_queue_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("Очередь задач")
        form = QFormLayout(group)

        self.poll_interval_spin = QDoubleSpinBox()
        self.poll_interval_spin.setRange(1.0, 120.0)
        self.poll_interval_spin.setSuffix(" сек")
        self.poll_interval_spin.setToolTip("Интервал проверки очереди")
        form.addRow("Интервал polling:", self.poll_interval_spin)

        self.poll_max_interval_spin = QDoubleSpinBox()
        self.poll_max_interval_spin.setRange(10.0, 300.0)
        self.poll_max_interval_spin.setSuffix(" сек")
        self.poll_max_interval_spin.setToolTip("Максимальный интервал при backoff")
        form.addRow("Макс. интервал:", self.poll_max_interval_spin)

        self.max_queue_size_spin = QSpinBox()
        self.max_queue_size_spin.setRange(10, 1000)
        self.max_queue_size_spin.setToolTip("Максимальный размер очереди Redis")
        form.addRow("Макс. размер очереди:", self.max_queue_size_spin)

        self.default_priority_spin = QSpinBox()
        self.default_priority_spin.setRange(1, 10)
        self.default_priority_spin.setToolTip("Приоритет задач (1=высший, 10=низший)")
        form.addRow("Приоритет по умолчанию:", self.default_priority_spin)

        layout.addWidget(group)

        # Информация
        info = QLabel(
            "ℹ️ Изменения вступят в силу после перезапуска OCR сервера.\n"
            "Текущие задачи продолжат выполняться со старыми настройками."
        )
        info.setStyleSheet("color: #888; font-size: 11px; padding: 10px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addStretch()

        return widget

    def _create_rate_limit_tab(self) -> QWidget:
        """Вкладка настроек Rate Limiting"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Группа: Datalab API
        group1 = QGroupBox("Datalab API")
        form1 = QFormLayout(group1)

        self.rate_datalab_rpm_spin = QSpinBox()
        self.rate_datalab_rpm_spin.setRange(10, 500)
        self.rate_datalab_rpm_spin.setSuffix(" req/min")
        self.rate_datalab_rpm_spin.setToolTip("Максимум запросов в минуту к Datalab API")
        form1.addRow("RPM лимит:", self.rate_datalab_rpm_spin)

        self.rate_datalab_concurrent_spin = QSpinBox()
        self.rate_datalab_concurrent_spin.setRange(1, 20)
        self.rate_datalab_concurrent_spin.setToolTip("Максимум параллельных запросов к Datalab")
        form1.addRow("Параллельных:", self.rate_datalab_concurrent_spin)

        layout.addWidget(group1)

        # Группа: OpenRouter API
        group2 = QGroupBox("OpenRouter API")
        form2 = QFormLayout(group2)

        self.rate_openrouter_rpm_spin = QSpinBox()
        self.rate_openrouter_rpm_spin.setRange(10, 500)
        self.rate_openrouter_rpm_spin.setSuffix(" req/min")
        self.rate_openrouter_rpm_spin.setToolTip("Максимум запросов в минуту к OpenRouter API")
        form2.addRow("RPM лимит:", self.rate_openrouter_rpm_spin)

        self.rate_openrouter_concurrent_spin = QSpinBox()
        self.rate_openrouter_concurrent_spin.setRange(1, 30)
        self.rate_openrouter_concurrent_spin.setToolTip("Максимум параллельных запросов к OpenRouter")
        form2.addRow("Параллельных:", self.rate_openrouter_concurrent_spin)

        layout.addWidget(group2)

        # Группа: Лимит на пользователя (fairness)
        group3 = QGroupBox("Лимит на пользователя (fairness)")
        form3 = QFormLayout(group3)

        self.rate_client_rpm_spin = QSpinBox()
        self.rate_client_rpm_spin.setRange(5, 200)
        self.rate_client_rpm_spin.setSuffix(" req/min")
        self.rate_client_rpm_spin.setToolTip(
            "Лимит запросов на одного пользователя.\n"
            "Обеспечивает честное распределение ресурсов."
        )
        form3.addRow("RPM на пользователя:", self.rate_client_rpm_spin)

        self.rate_client_concurrent_spin = QSpinBox()
        self.rate_client_concurrent_spin.setRange(1, 10)
        self.rate_client_concurrent_spin.setToolTip("Максимум параллельных запросов на пользователя")
        form3.addRow("Параллельных на user:", self.rate_client_concurrent_spin)

        layout.addWidget(group3)

        # Группа: Backoff при 429 ошибках
        group4 = QGroupBox("Backoff при 429 ошибках")
        form4 = QFormLayout(group4)

        self.rate_backoff_base_spin = QDoubleSpinBox()
        self.rate_backoff_base_spin.setRange(1.0, 30.0)
        self.rate_backoff_base_spin.setSuffix(" сек")
        self.rate_backoff_base_spin.setDecimals(1)
        self.rate_backoff_base_spin.setToolTip(
            "Начальная задержка при получении 429 от API.\n"
            "Экспоненциально увеличивается при повторных ошибках."
        )
        form4.addRow("Базовая задержка:", self.rate_backoff_base_spin)

        self.rate_backoff_max_spin = QDoubleSpinBox()
        self.rate_backoff_max_spin.setRange(10.0, 300.0)
        self.rate_backoff_max_spin.setSuffix(" сек")
        self.rate_backoff_max_spin.setDecimals(1)
        self.rate_backoff_max_spin.setToolTip("Максимальная задержка при экспоненциальном backoff")
        form4.addRow("Макс. задержка:", self.rate_backoff_max_spin)

        layout.addWidget(group4)

        # Информация
        info = QLabel(
            "ℹ️ Rate limiting распределён через Redis.\n"
            "Лимиты применяются ко всему кластеру воркеров."
        )
        info.setStyleSheet("color: #888; font-size: 11px; padding: 10px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addStretch()

        return widget

    def _load_settings(self):
        """Загрузить настройки из Supabase"""
        try:
            url = f"{self.client.supabase_url}/rest/v1/app_settings?key=eq.{self.SETTINGS_KEY}"
            headers = {
                "apikey": self.client.supabase_key,
                "Authorization": f"Bearer {self.client.supabase_key}",
            }
            client = _get_tree_client()
            resp = client.get(url, headers=headers, timeout=30.0)

            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    settings_data = data[0].get("value", {})
                    self.settings = OCRSettings.from_dict(settings_data)

        except Exception as e:
            logger.warning(f"Failed to load OCR settings: {e}")

        self._update_ui_from_settings()

    def _update_ui_from_settings(self):
        """Обновить UI из настроек"""
        s = self.settings

        # Worker
        self.max_concurrent_jobs_spin.setValue(s.max_concurrent_jobs)
        self.worker_prefetch_spin.setValue(s.worker_prefetch)
        self.worker_max_tasks_spin.setValue(s.worker_max_tasks)
        self.task_soft_timeout_spin.setValue(s.task_soft_timeout)
        self.task_hard_timeout_spin.setValue(s.task_hard_timeout)
        self.task_max_retries_spin.setValue(s.task_max_retries)
        self.task_retry_delay_spin.setValue(s.task_retry_delay)

        # OCR
        self.max_global_ocr_spin.setValue(s.max_global_ocr_requests)
        self.ocr_threads_per_job_spin.setValue(s.ocr_threads_per_job)
        self.ocr_request_timeout_spin.setValue(s.ocr_request_timeout)
        self.datalab_max_rpm_spin.setValue(s.datalab_max_rpm)
        self.datalab_max_concurrent_spin.setValue(s.datalab_max_concurrent)
        self.datalab_poll_interval_spin.setValue(s.datalab_poll_interval)
        self.datalab_poll_max_attempts_spin.setValue(s.datalab_poll_max_attempts)
        self.datalab_max_retries_spin.setValue(s.datalab_max_retries)

        # Algorithm
        self.use_two_pass_check.setChecked(s.use_two_pass_ocr)
        self.crop_png_compress_spin.setValue(s.crop_png_compress)
        self.max_ocr_batch_spin.setValue(s.max_ocr_batch_size)
        self.pdf_render_dpi_spin.setValue(s.pdf_render_dpi)
        self.max_strip_height_spin.setValue(s.max_strip_height)
        self.block_separator_height_spin.setValue(s.block_separator_height)

        # Queue
        self.poll_interval_spin.setValue(s.poll_interval)
        self.poll_max_interval_spin.setValue(s.poll_max_interval)
        self.max_queue_size_spin.setValue(s.max_queue_size)
        self.default_priority_spin.setValue(s.default_task_priority)

        # Rate Limit
        self.rate_datalab_rpm_spin.setValue(s.rate_limit_datalab_rpm)
        self.rate_datalab_concurrent_spin.setValue(s.rate_limit_datalab_concurrent)
        self.rate_openrouter_rpm_spin.setValue(s.rate_limit_openrouter_rpm)
        self.rate_openrouter_concurrent_spin.setValue(s.rate_limit_openrouter_concurrent)
        self.rate_client_rpm_spin.setValue(s.rate_limit_client_rpm)
        self.rate_client_concurrent_spin.setValue(s.rate_limit_client_concurrent)
        self.rate_backoff_base_spin.setValue(s.rate_limit_backoff_base)
        self.rate_backoff_max_spin.setValue(s.rate_limit_backoff_max)

    def _update_settings_from_ui(self):
        """Обновить настройки из UI"""
        self.settings = OCRSettings(
            # Worker
            max_concurrent_jobs=self.max_concurrent_jobs_spin.value(),
            worker_prefetch=self.worker_prefetch_spin.value(),
            worker_max_tasks=self.worker_max_tasks_spin.value(),
            task_soft_timeout=self.task_soft_timeout_spin.value(),
            task_hard_timeout=self.task_hard_timeout_spin.value(),
            task_max_retries=self.task_max_retries_spin.value(),
            task_retry_delay=self.task_retry_delay_spin.value(),
            # OCR
            max_global_ocr_requests=self.max_global_ocr_spin.value(),
            ocr_threads_per_job=self.ocr_threads_per_job_spin.value(),
            ocr_request_timeout=self.ocr_request_timeout_spin.value(),
            datalab_max_rpm=self.datalab_max_rpm_spin.value(),
            datalab_max_concurrent=self.datalab_max_concurrent_spin.value(),
            datalab_poll_interval=self.datalab_poll_interval_spin.value(),
            datalab_poll_max_attempts=self.datalab_poll_max_attempts_spin.value(),
            datalab_max_retries=self.datalab_max_retries_spin.value(),
            # Algorithm
            use_two_pass_ocr=self.use_two_pass_check.isChecked(),
            crop_png_compress=self.crop_png_compress_spin.value(),
            max_ocr_batch_size=self.max_ocr_batch_spin.value(),
            pdf_render_dpi=self.pdf_render_dpi_spin.value(),
            max_strip_height=self.max_strip_height_spin.value(),
            block_separator_height=self.block_separator_height_spin.value(),
            # Queue
            poll_interval=self.poll_interval_spin.value(),
            poll_max_interval=self.poll_max_interval_spin.value(),
            max_queue_size=self.max_queue_size_spin.value(),
            default_task_priority=self.default_priority_spin.value(),
            # Rate Limit
            rate_limit_datalab_rpm=self.rate_datalab_rpm_spin.value(),
            rate_limit_datalab_concurrent=self.rate_datalab_concurrent_spin.value(),
            rate_limit_openrouter_rpm=self.rate_openrouter_rpm_spin.value(),
            rate_limit_openrouter_concurrent=self.rate_openrouter_concurrent_spin.value(),
            rate_limit_client_rpm=self.rate_client_rpm_spin.value(),
            rate_limit_client_concurrent=self.rate_client_concurrent_spin.value(),
            rate_limit_backoff_base=self.rate_backoff_base_spin.value(),
            rate_limit_backoff_max=self.rate_backoff_max_spin.value(),
        )

    def _save_settings(self):
        """Сохранить настройки в Supabase"""
        self._update_settings_from_ui()

        try:
            # Upsert в app_settings
            url = f"{self.client.supabase_url}/rest/v1/app_settings"
            headers = {
                "apikey": self.client.supabase_key,
                "Authorization": f"Bearer {self.client.supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            }
            data = {
                "key": self.SETTINGS_KEY,
                "value": self.settings.to_dict(),
            }
            client = _get_tree_client()
            resp = client.post(url, headers=headers, json=data, timeout=30.0)
            resp.raise_for_status()

            QMessageBox.information(
                self,
                "Сохранено",
                "Настройки сохранены.\n\n"
                "Изменения вступят в силу после перезапуска OCR сервера.",
            )
            self.accept()

        except Exception as e:
            logger.error(f"Failed to save OCR settings: {e}")
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить настройки:\n{e}"
            )

    def _reset_defaults(self):
        """Сбросить к значениям по умолчанию"""
        reply = QMessageBox.question(
            self, "Подтверждение", "Сбросить все настройки к значениям по умолчанию?"
        )
        if reply == QMessageBox.Yes:
            self.settings = OCRSettings()
            self._update_ui_from_settings()

    def _export_all_settings(self):
        """Экспортировать все настройки из БД в JSON файл"""
        try:
            # Запрашиваем путь для сохранения
            default_filename = (
                f"ocr_settings_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить настройки",
                default_filename,
                "JSON файлы (*.json);;Все файлы (*)",
            )

            if not file_path:
                return  # Пользователь отменил

            # Получаем все настройки из таблицы app_settings
            url = f"{self.client.supabase_url}/rest/v1/app_settings?select=*"
            headers = {
                "apikey": self.client.supabase_key,
                "Authorization": f"Bearer {self.client.supabase_key}",
            }
            client = _get_tree_client()
            resp = client.get(url, headers=headers, timeout=30.0)
            resp.raise_for_status()

            all_settings = resp.json()

            # Сохраняем в файл с красивым форматированием
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(all_settings, f, ensure_ascii=False, indent=2)

            QMessageBox.information(
                self,
                "Успешно",
                f"Настройки успешно экспортированы.\n\n"
                f"Файл: {file_path}\n"
                f"Экспортировано записей: {len(all_settings)}",
            )
            logger.info(f"Exported {len(all_settings)} settings to {file_path}")

        except Exception as e:
            logger.error(f"Failed to export settings: {e}")
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось экспортировать настройки:\n{e}"
            )
