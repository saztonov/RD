"""Диалог с детальной информацией о задаче OCR"""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.gui.utils import format_datetime_utc3

if TYPE_CHECKING:
    pass


class JobDetailsDialog(QDialog):
    """Диалог с детальной информацией о задаче"""

    def __init__(self, job_details: dict, parent=None):
        super().__init__(parent)
        self.job_details = job_details
        self.setWindowTitle("Информация о задаче")
        self.setMinimumWidth(500)
        self._setup_ui()

    def _setup_ui(self):
        """Настроить UI"""
        layout = QVBoxLayout(self)

        # Основная информация
        main_group = QGroupBox("Основная информация")
        main_layout = QFormLayout()

        # ID задачи (полный) с кнопкой копирования
        job_id = self.job_details.get("id", "")
        job_id_layout = QHBoxLayout()
        job_id_label = QLabel(job_id)
        job_id_layout.addWidget(job_id_label, 1)

        copy_btn = QPushButton("📋")
        copy_btn.setMaximumWidth(30)
        copy_btn.setToolTip("Скопировать ID в буфер обмена")
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(job_id))
        job_id_layout.addWidget(copy_btn)

        main_layout.addRow("ID задачи:", job_id_layout)

        # ID папки на R2 (извлекаем из r2_prefix)
        r2_prefix = self.job_details.get("r2_prefix", "")
        if r2_prefix:
            folder_id = r2_prefix.rstrip("/").split("/")[-1]
            folder_id_layout = QHBoxLayout()
            folder_id_label = QLabel(folder_id)
            folder_id_layout.addWidget(folder_id_label, 1)

            copy_folder_btn = QPushButton("📋")
            copy_folder_btn.setMaximumWidth(30)
            copy_folder_btn.setToolTip("Скопировать ID папки в буфер обмена")
            copy_folder_btn.clicked.connect(lambda: self._copy_to_clipboard(folder_id))
            folder_id_layout.addWidget(copy_folder_btn)

            main_layout.addRow("ID папки:", folder_id_layout)

        # Документ
        doc_name = self.job_details.get("document_name", "")
        main_layout.addRow("Документ:", QLabel(doc_name))

        # Engine
        engine = self.job_details.get("engine", "")
        engine_label = {
            "openrouter": "OpenRouter",
            "datalab": "Datalab",
            "local": "Локальный",
        }.get(engine, engine)
        main_layout.addRow("Движок:", QLabel(engine_label))

        # Статус
        status = self.job_details.get("status", "")
        status_label = {
            "queued": "⏳ В очереди",
            "processing": "🔄 Обработка",
            "done": "✅ Готово",
            "error": "❌ Ошибка",
        }.get(status, status)
        main_layout.addRow("Статус:", QLabel(status_label))

        # Прогресс
        progress = self.job_details.get("progress", 0)
        main_layout.addRow("Прогресс:", QLabel(f"{int(progress * 100)}%"))

        main_group.setLayout(main_layout)
        layout.addWidget(main_group)

        # Статистика блоков
        block_stats = self.job_details.get("block_stats", {})
        if block_stats:
            blocks_group = QGroupBox("Статистика блоков")
            blocks_layout = QFormLayout()

            total = block_stats.get("total", 0)
            text_count = block_stats.get("text", 0)
            table_count = block_stats.get("table", 0)
            image_count = block_stats.get("image", 0)
            stamp_count = block_stats.get("stamp", 0)
            grouped_count = block_stats.get("grouped", text_count + table_count)

            # Время обработки (processing_time_seconds или total_time_seconds для обратной совместимости)
            processing_time = block_stats.get("processing_time_seconds") or block_stats.get("total_time_seconds")
            if processing_time:
                blocks_layout.addRow("⏱ Время обработки:", QLabel(self._format_duration(processing_time)))

            blocks_layout.addRow("Всего блоков:", QLabel(str(total)))

            # Текстовые блоки с временем
            text_time = block_stats.get("estimated_text_time")
            if text_count > 0 and text_time:
                avg_text = text_time / text_count if text_count > 0 else 0
                text_info = f"{text_count}  ({self._format_duration(text_time)}, ~{self._format_duration(avg_text)}/блок)"
            else:
                text_info = str(text_count)
            blocks_layout.addRow("Текстовых:", QLabel(text_info))

            # Таблицы с временем
            table_time = block_stats.get("estimated_table_time")
            if table_count > 0 and table_time:
                avg_table = table_time / table_count if table_count > 0 else 0
                table_info = f"{table_count}  ({self._format_duration(table_time)}, ~{self._format_duration(avg_table)}/блок)"
            else:
                table_info = str(table_count)
            blocks_layout.addRow("Таблиц:", QLabel(table_info))

            # Изображения с временем
            image_time = block_stats.get("estimated_image_time")
            if image_count > 0 and image_time:
                avg_image = image_time / image_count if image_count > 0 else 0
                image_info = f"{image_count}  ({self._format_duration(image_time)}, ~{self._format_duration(avg_image)}/блок)"
            else:
                image_info = str(image_count)
            blocks_layout.addRow("Изображений:", QLabel(image_info))

            # Штампы с временем
            stamp_time = block_stats.get("estimated_stamp_time")
            if stamp_count > 0:
                if stamp_time:
                    avg_stamp = stamp_time / stamp_count if stamp_count > 0 else 0
                    stamp_info = f"{stamp_count}  ({self._format_duration(stamp_time)}, ~{self._format_duration(avg_stamp)}/блок)"
                else:
                    stamp_info = str(stamp_count)
                blocks_layout.addRow("Штампов:", QLabel(stamp_info))

            # Сгруппировано (текст + таблицы)
            blocks_layout.addRow("Сгруппировано (текст+таблицы):", QLabel(str(grouped_count)))

            # Среднее время на блок
            avg_per_block = block_stats.get("avg_time_per_block")
            if avg_per_block and total > 0:
                blocks_layout.addRow("Среднее время/блок:", QLabel(self._format_duration(avg_per_block)))

            blocks_group.setLayout(blocks_layout)
            layout.addWidget(blocks_group)

        # Временные метки
        time_group = QGroupBox("Временные метки")
        time_layout = QFormLayout()

        # Дата создания
        created_at = self.job_details.get("created_at", "")
        if created_at:
            created_str = format_datetime_utc3(created_at)
            time_layout.addRow("Создание задачи (МСК):", QLabel(created_str))

        # Дата начала обработки
        started_at = self.job_details.get("started_at", "")
        if started_at:
            started_str = format_datetime_utc3(started_at)
            time_layout.addRow("Начало обработки (МСК):", QLabel(started_str))

        # Дата завершения
        completed_at = self.job_details.get("completed_at", "")
        if completed_at:
            completed_str = format_datetime_utc3(completed_at)
            time_layout.addRow("Завершение (МСК):", QLabel(completed_str))

        # Время обработки (из block_stats или вычисляем)
        processing_time = block_stats.get("processing_time_seconds") if block_stats else None
        if processing_time:
            time_layout.addRow("⏱ Время обработки:", QLabel(self._format_duration(processing_time)))
        elif started_at and completed_at:
            try:
                started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                completed_dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                processing_time = (completed_dt - started_dt).total_seconds()
                time_layout.addRow("⏱ Время обработки:", QLabel(self._format_duration(processing_time)))
            except Exception:
                pass

        # Прошло времени (для активных задач)
        if status in ("queued", "processing") and created_at:
            try:
                created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                elapsed = (now - created_dt).total_seconds()
                elapsed_label = QLabel(self._format_duration(elapsed))
                elapsed_label.setStyleSheet("color: #ffa500;")  # Оранжевый для активных
                time_layout.addRow("⏳ Прошло времени:", elapsed_label)
            except Exception:
                pass

        # Дата обновления (только если отличается от завершения)
        updated_at = self.job_details.get("updated_at", "")
        if updated_at and updated_at != completed_at:
            updated_str = format_datetime_utc3(updated_at)
            time_layout.addRow("Последнее обновление:", QLabel(updated_str))

        # Прогнозная дата окончания (только для processing)
        if status == "processing" and progress > 0:
            estimate = self._estimate_completion(created_at, progress)
            if estimate:
                time_layout.addRow("Прогноз завершения (МСК):", QLabel(estimate))

        time_group.setLayout(time_layout)
        layout.addWidget(time_group)

        # Батчи (если доступно)
        num_pages = self.job_details.get("num_pages")
        if num_pages:
            batch_group = QGroupBox("Обработка")
            batch_layout = QFormLayout()
            batch_layout.addRow("Страниц:", QLabel(str(num_pages)))
            batch_group.setLayout(batch_layout)
            layout.addWidget(batch_group)

        # Пути к файлам
        paths_group = QGroupBox("Расположение файлов")
        paths_layout = QVBoxLayout()

        # Локальная папка клиента (output_dir из настроек OCR)
        client_output_dir = self.job_details.get("client_output_dir")
        if client_output_dir:
            local_layout = QHBoxLayout()

            # Проверяем существование папки
            folder_exists = os.path.exists(client_output_dir)

            if folder_exists:
                local_label = QLabel(f"Локально: {client_output_dir}")
                local_label.setWordWrap(True)
                local_layout.addWidget(local_label, 1)

                open_local_btn = QPushButton("📁 Открыть")
                open_local_btn.setMaximumWidth(100)
                open_local_btn.clicked.connect(
                    lambda: self._open_folder(client_output_dir)
                )
                local_layout.addWidget(open_local_btn)
            else:
                local_label = QLabel(
                    f"Локально: {client_output_dir} (результат еще не скачан)"
                )
                local_label.setStyleSheet("color: gray;")
                local_label.setWordWrap(True)
                local_layout.addWidget(local_label, 1)

            paths_layout.addLayout(local_layout)

        # Серверная папка (job_dir на сервере) - для справки
        job_dir = self.job_details.get("job_dir")
        if job_dir and not client_output_dir:
            # Показываем только если нет client_output_dir
            server_layout = QHBoxLayout()
            server_label = QLabel(f"На сервере: {job_dir}")
            server_label.setWordWrap(True)
            server_label.setStyleSheet("color: gray;")
            server_layout.addWidget(server_label, 1)
            paths_layout.addLayout(server_layout)

        # R2 Storage
        r2_base_url = self.job_details.get("r2_base_url")
        r2_files = self.job_details.get("r2_files", [])
        if r2_base_url:
            r2_layout = QHBoxLayout()

            r2_label = QLabel(f"R2 Storage: {r2_base_url}")
            r2_label.setWordWrap(True)
            r2_layout.addWidget(r2_label, 1)

            if r2_files:
                open_r2_btn = QPushButton("📦 Файлы")
                open_r2_btn.setToolTip("Открыть список файлов на R2")
                open_r2_btn.setMaximumWidth(100)
                open_r2_btn.clicked.connect(
                    lambda: self._show_r2_files(r2_base_url, r2_files)
                )
                r2_layout.addWidget(open_r2_btn)

            paths_layout.addLayout(r2_layout)
        elif self.job_details.get("status") == "done":
            # Если задача готова, но нет r2_prefix - значит R2 не настроен или ошибка
            r2_error_layout = QHBoxLayout()
            r2_error_label = QLabel(
                "R2 Storage: не загружено (проверьте настройки сервера)"
            )
            r2_error_label.setStyleSheet("color: orange;")
            r2_error_layout.addWidget(r2_error_label, 1)
            paths_layout.addLayout(r2_error_layout)

        paths_group.setLayout(paths_layout)
        layout.addWidget(paths_group)

        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _copy_to_clipboard(self, text: str):
        """Скопировать текст в буфер обмена"""
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)

    def _open_folder(self, path: str):
        """Открыть папку в проводнике"""
        try:
            if not os.path.exists(path):
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "Ошибка", f"Папка не найдена:\n{path}")
                return

            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть папку:\n{e}")

    def _show_r2_files(self, r2_base_url: str, r2_files: list):
        """Показать диалог со списком файлов на R2"""
        from app.gui.r2_viewer import R2FilesDialog

        dialog = R2FilesDialog(r2_base_url, r2_files, self)
        dialog.exec()

    def _open_r2_url(self, url: str):
        """Открыть URL в браузере"""
        webbrowser.open(url)

    def _format_duration(self, seconds: float) -> str:
        """Форматировать длительность в человекочитаемый формат"""
        if seconds < 1:
            return f"{seconds * 1000:.0f}мс"
        elif seconds < 60:
            return f"{seconds:.1f}с"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}м {secs}с"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours}ч {minutes}м {secs}с"

    def _estimate_completion(self, created_at: str, progress: float) -> str:
        """Прогноз времени завершения (в UTC+3)"""
        try:
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            elapsed = (now - created_dt).total_seconds()

            if progress > 0.01:  # Минимум 1% для оценки
                total_seconds = elapsed / progress
                remaining_seconds = total_seconds - elapsed

                if remaining_seconds > 0:
                    eta_dt = now + timedelta(seconds=remaining_seconds)

                    # Конвертируем в UTC+3
                    utc3 = timezone(timedelta(hours=3))
                    eta_local = eta_dt.astimezone(utc3)
                    eta_str = eta_local.strftime("%H:%M %d.%m.%Y")

                    # Форматируем оставшееся время
                    remaining = timedelta(seconds=int(remaining_seconds))
                    hours, remainder = divmod(remaining.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)

                    if remaining.days > 0:
                        time_left = f"{remaining.days}д {hours}ч {minutes}м"
                    elif hours > 0:
                        time_left = f"{hours}ч {minutes}м"
                    else:
                        time_left = f"{minutes}м {seconds}с"

                    return f"{eta_str} (~{time_left})"
        except:
            pass

        return ""
