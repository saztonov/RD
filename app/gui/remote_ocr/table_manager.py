"""Управление таблицей задач Remote OCR"""

import logging
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidgetItem,
    QWidget,
)

from app.gui.utils import format_datetime_utc3

logger = logging.getLogger(__name__)


class TableManagerMixin:
    """Миксин для управления таблицей задач"""

    def _update_table(self, jobs):
        """Обновить таблицу задач"""
        self.jobs_table.setSortingEnabled(False)
        self.jobs_table.setRowCount(0)

        # Авто-скачивание результата для текущего документа (только один раз)
        current_node_id = getattr(self.main_window, "_current_node_id", None)
        if current_node_id:
            for job in jobs:
                if (
                    job.status == "done"
                    and getattr(job, "node_id", None) == current_node_id
                ):
                    if job.id not in self._downloaded_jobs:
                        self._auto_download_result(job.id)
                    break  # Только последняя done задача для текущего документа

        for idx, job in enumerate(jobs, start=1):
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)

            num_item = QTableWidgetItem(str(idx))
            num_item.setData(Qt.UserRole, job.id)
            self.jobs_table.setItem(row, 0, num_item)

            display_name = job.task_name if job.task_name else job.document_name
            self.jobs_table.setItem(row, 1, QTableWidgetItem(display_name))

            created_at_str = format_datetime_utc3(job.created_at)
            created_item = QTableWidgetItem(created_at_str)
            created_item.setData(Qt.UserRole, job.created_at)
            self.jobs_table.setItem(row, 2, created_item)

            status_text = self._get_status_text(job.status)
            status_item = QTableWidgetItem(status_text)
            if job.error_message:
                status_item.setToolTip(job.error_message)
            self.jobs_table.setItem(row, 3, status_item)

            progress_text = f"{int(job.progress * 100)}%"
            progress_item = QTableWidgetItem(progress_text)
            progress_item.setData(Qt.UserRole, job.progress)
            self.jobs_table.setItem(row, 4, progress_item)

            status_msg = job.status_message or ""
            status_msg_item = QTableWidgetItem(status_msg)
            self.jobs_table.setItem(row, 5, status_msg_item)

            actions_widget = self._create_actions_widget(job)
            self.jobs_table.setCellWidget(row, 6, actions_widget)

        self.jobs_table.setSortingEnabled(True)

    def _add_job_to_table(self, job, at_top: bool = False):
        """Добавить одну задачу в таблицу (для оптимистичного обновления)"""
        logger.info(
            f"_add_job_to_table: job_id={job.id}, at_top={at_top}, "
            f"current_rows={self.jobs_table.rowCount()}"
        )

        self.jobs_table.setSortingEnabled(False)

        row = 0 if at_top else self.jobs_table.rowCount()
        self.jobs_table.insertRow(row)

        num_item = QTableWidgetItem("1" if at_top else str(self.jobs_table.rowCount()))
        num_item.setData(Qt.UserRole, job.id)
        self.jobs_table.setItem(row, 0, num_item)

        display_name = job.task_name if job.task_name else job.document_name
        self.jobs_table.setItem(row, 1, QTableWidgetItem(display_name))

        created_at_str = (
            format_datetime_utc3(job.created_at) if job.created_at else "Только что"
        )
        created_item = QTableWidgetItem(created_at_str)
        created_item.setData(Qt.UserRole, job.created_at)
        self.jobs_table.setItem(row, 2, created_item)

        status_text = self._get_status_text(job.status)
        self.jobs_table.setItem(row, 3, QTableWidgetItem(status_text))

        progress_text = f"{int(job.progress * 100)}%"
        progress_item = QTableWidgetItem(progress_text)
        progress_item.setData(Qt.UserRole, job.progress)
        self.jobs_table.setItem(row, 4, progress_item)

        status_msg = job.status_message or ""
        status_msg_item = QTableWidgetItem(status_msg)
        self.jobs_table.setItem(row, 5, status_msg_item)

        actions_widget = self._create_actions_widget(job)
        self.jobs_table.setCellWidget(row, 6, actions_widget)

        self.jobs_table.setSortingEnabled(True)

        logger.info(
            f"Задача добавлена в таблицу: row={row}, name={display_name}, "
            f"status={job.status}, total_rows={self.jobs_table.rowCount()}"
        )

    def _replace_job_in_table(self, old_job_id: str, new_job):
        """Заменить временную задачу на реальную в таблице"""
        for row in range(self.jobs_table.rowCount()):
            item = self.jobs_table.item(row, 0)
            if item and item.data(Qt.UserRole) == old_job_id:
                logger.info(
                    f"Найдена временная задача в строке {row}, заменяем на {new_job.id}"
                )

                item.setData(Qt.UserRole, new_job.id)

                display_name = (
                    new_job.task_name if new_job.task_name else new_job.document_name
                )
                self.jobs_table.item(row, 1).setText(display_name)

                created_at_str = (
                    format_datetime_utc3(new_job.created_at)
                    if new_job.created_at
                    else "Только что"
                )
                self.jobs_table.item(row, 2).setText(created_at_str)

                status_text = self._get_status_text(new_job.status)
                self.jobs_table.item(row, 3).setText(status_text)

                progress_text = f"{int(new_job.progress * 100)}%"
                self.jobs_table.item(row, 4).setText(progress_text)

                status_msg = new_job.status_message or ""
                self.jobs_table.item(row, 5).setText(status_msg)

                actions_widget = self._create_actions_widget(new_job)
                self.jobs_table.setCellWidget(row, 6, actions_widget)

                logger.info(f"Задача заменена: {old_job_id} -> {new_job.id}")
                return

        logger.warning(
            f"Временная задача {old_job_id} не найдена в таблице, добавляем как новую"
        )
        self._add_job_to_table(new_job, at_top=True)

    def _remove_job_from_table(self, job_id: str):
        """Удалить задачу из таблицы по ID"""
        for row in range(self.jobs_table.rowCount()):
            item = self.jobs_table.item(row, 0)
            if item and item.data(Qt.UserRole) == job_id:
                self.jobs_table.removeRow(row)
                logger.info(f"Задача {job_id} удалена из таблицы")
                return

    def _get_status_text(self, status: str) -> str:
        """Получить текст статуса с эмодзи"""
        return {
            "uploading": "⬆️ Загрузка...",
            "draft": "📝 Черновик",
            "queued": "⏳ В очереди",
            "processing": "🔄 Обработка",
            "done": "✅ Готово",
            "error": "❌ Ошибка",
            "paused": "⏸️ Пауза",
            "cancelled": "🚫 Отменено",
        }.get(status, status)

    def _create_actions_widget(self, job) -> QWidget:
        """Создать виджет с кнопками действий для задачи"""
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(1, 1, 1, 1)
        actions_layout.setSpacing(2)

        # Кнопка остановки для активных задач
        if job.status in ("queued", "processing"):
            stop_btn = QPushButton("⏹")
            stop_btn.setToolTip("Отменить задачу")
            stop_btn.setFixedSize(26, 26)
            stop_btn.setStyleSheet(
                "QPushButton { background-color: #c0392b; border: 1px solid #922b21; "
                "border-radius: 4px; color: white; font-weight: bold; } "
                "QPushButton:hover { background-color: #922b21; }"
            )
            stop_btn.clicked.connect(lambda checked, jid=job.id: self._cancel_job(jid))
            actions_layout.addWidget(stop_btn)
        elif job.status == "paused":
            resume_btn = QPushButton("▶")
            resume_btn.setToolTip("Возобновить")
            resume_btn.setFixedSize(26, 26)
            resume_btn.setStyleSheet(
                "QPushButton { background-color: #27ae60; border: 1px solid #1e8449; "
                "border-radius: 4px; color: white; } "
                "QPushButton:hover { background-color: #1e8449; }"
            )
            resume_btn.clicked.connect(
                lambda checked, jid=job.id: self._resume_job(jid)
            )
            actions_layout.addWidget(resume_btn)

        # Кнопка информации
        info_btn = QPushButton("ℹ")
        info_btn.setToolTip("Информация о задаче")
        info_btn.setFixedSize(26, 26)
        info_btn.setStyleSheet(
            "QPushButton { background-color: #3498db; border: 1px solid #2980b9; "
            "border-radius: 4px; color: white; font-weight: bold; } "
            "QPushButton:hover { background-color: #2980b9; }"
        )
        info_btn.clicked.connect(
            lambda checked, jid=job.id: self._show_job_details(jid)
        )
        actions_layout.addWidget(info_btn)

        actions_layout.addStretch()
        return actions_widget
