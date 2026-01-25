"""Диалог сверки файлов между R2 и Supabase."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .types import DiscrepancyType, FileDiscrepancy
from .worker import ReconciliationWorker

if TYPE_CHECKING:
    from app.tree_client import TreeClient, TreeNode

logger = logging.getLogger(__name__)


class FileReconciliationDialog(QDialog):
    """Диалог для сверки и исправления несоответствий между R2 и Supabase"""

    def __init__(self, node: "TreeNode", client: "TreeClient", parent=None):
        super().__init__(parent)
        self.node = node
        self.client = client
        self.discrepancies: List[FileDiscrepancy] = []
        self.worker: Optional[ReconciliationWorker] = None

        self.setWindowTitle(f"Сверка файлов: {node.name}")
        self.resize(1000, 700)
        self._setup_ui()
        self._start_reconciliation()

    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)

        # Информация о документе
        info_label = QLabel(
            f"<b>Документ:</b> {self.node.name}<br>"
            f"<b>ID:</b> {self.node.id}<br>"
            f"<b>R2 Key:</b> {self.node.attributes.get('r2_key', 'N/A')}"
        )
        layout.addWidget(info_label)

        # Прогресс
        self.progress_label = QLabel("Запуск сверки...")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.progress_bar)

        # Табы для разных типов несоответствий
        self.tabs = QTabWidget()

        # Вкладка: Файлы-сироты в R2 (нет в БД)
        self.orphan_r2_widget = QWidget()
        self._setup_table_widget(self.orphan_r2_widget, "orphan_r2")
        self.tabs.addTab(self.orphan_r2_widget, "R2 (нет в БД)")

        # Вкладка: Записи-сироты в БД (нет в R2)
        self.orphan_db_widget = QWidget()
        self._setup_table_widget(self.orphan_db_widget, "orphan_db")
        self.tabs.addTab(self.orphan_db_widget, "БД (нет в R2)")

        # Вкладка: Несовпадение размеров
        self.size_mismatch_widget = QWidget()
        self._setup_table_widget(self.size_mismatch_widget, "size_mismatch")
        self.tabs.addTab(self.size_mismatch_widget, "Размер не совпадает")

        layout.addWidget(self.tabs)

        # Кнопки действий
        action_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self._start_reconciliation)
        self.refresh_btn.setEnabled(False)
        action_layout.addWidget(self.refresh_btn)

        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.clicked.connect(self._select_all_current_tab)
        action_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Снять выбор")
        self.deselect_all_btn.clicked.connect(self._deselect_all_current_tab)
        action_layout.addWidget(self.deselect_all_btn)

        action_layout.addStretch()

        self.delete_r2_btn = QPushButton("Удалить выбранные из R2")
        self.delete_r2_btn.setStyleSheet("background-color: #d9534f; color: white;")
        self.delete_r2_btn.clicked.connect(self._delete_selected_from_r2)
        action_layout.addWidget(self.delete_r2_btn)

        self.delete_db_btn = QPushButton("Удалить выбранные из БД")
        self.delete_db_btn.setStyleSheet("background-color: #f0ad4e; color: white;")
        self.delete_db_btn.clicked.connect(self._delete_selected_from_db)
        action_layout.addWidget(self.delete_db_btn)

        layout.addLayout(action_layout)

        # Кнопка закрытия
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _setup_table_widget(self, widget: QWidget, table_name: str):
        """Настроить виджет с таблицей"""
        layout = QVBoxLayout(widget)

        table = QTableWidget()
        table.setObjectName(f"table_{table_name}")
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["", "R2 Key", "Тип файла", "Размер R2", "Размер БД"])
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setColumnWidth(0, 30)
        table.setColumnWidth(2, 100)
        table.setColumnWidth(3, 100)
        table.setColumnWidth(4, 100)

        layout.addWidget(table)

        # Метка с итогом
        count_label = QLabel("Записей: 0")
        count_label.setObjectName(f"count_{table_name}")
        layout.addWidget(count_label)

    def _get_table(self, table_name: str) -> QTableWidget:
        """Получить таблицу по имени"""
        if table_name == "orphan_r2":
            return self.orphan_r2_widget.findChild(QTableWidget, "table_orphan_r2")
        elif table_name == "orphan_db":
            return self.orphan_db_widget.findChild(QTableWidget, "table_orphan_db")
        else:
            return self.size_mismatch_widget.findChild(QTableWidget, "table_size_mismatch")

    def _get_count_label(self, table_name: str) -> QLabel:
        """Получить метку количества"""
        if table_name == "orphan_r2":
            return self.orphan_r2_widget.findChild(QLabel, "count_orphan_r2")
        elif table_name == "orphan_db":
            return self.orphan_db_widget.findChild(QLabel, "count_orphan_db")
        else:
            return self.size_mismatch_widget.findChild(QLabel, "count_size_mismatch")

    def _start_reconciliation(self):
        """Запустить процесс сверки"""
        self.refresh_btn.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("Запуск сверки...")

        # Очищаем таблицы
        for name in ["orphan_r2", "orphan_db", "size_mismatch"]:
            table = self._get_table(name)
            if table:
                table.setRowCount(0)
            label = self._get_count_label(name)
            if label:
                label.setText("Записей: 0")

        # Обновляем заголовки табов
        self.tabs.setTabText(0, "R2 (нет в БД)")
        self.tabs.setTabText(1, "БД (нет в R2)")
        self.tabs.setTabText(2, "Размер не совпадает")

        # Запускаем воркер
        self.worker = ReconciliationWorker(self.node, self.client, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, message: str):
        """Обновить прогресс"""
        self.progress_label.setText(message)

    def _on_error(self, error: str):
        """Обработать ошибку"""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"Ошибка: {error}")
        self.refresh_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка сверки", f"Произошла ошибка:\n{error}")

    def _on_finished(self, discrepancies: List[FileDiscrepancy]):
        """Обработать результаты сверки"""
        self.discrepancies = discrepancies
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.refresh_btn.setEnabled(True)

        # Группируем по типу
        orphan_r2 = [d for d in discrepancies if d.discrepancy_type == DiscrepancyType.ORPHAN_R2]
        orphan_db = [d for d in discrepancies if d.discrepancy_type == DiscrepancyType.ORPHAN_DB]
        size_mismatch = [d for d in discrepancies if d.discrepancy_type == DiscrepancyType.SIZE_MISMATCH]

        # Заполняем таблицы
        self._populate_table("orphan_r2", orphan_r2)
        self._populate_table("orphan_db", orphan_db)
        self._populate_table("size_mismatch", size_mismatch)

        # Обновляем заголовки табов
        self.tabs.setTabText(0, f"R2 (нет в БД) [{len(orphan_r2)}]")
        self.tabs.setTabText(1, f"БД (нет в R2) [{len(orphan_db)}]")
        self.tabs.setTabText(2, f"Размер не совпадает [{len(size_mismatch)}]")

        if not discrepancies:
            self.progress_label.setText("Все файлы синхронизированы!")
        else:
            self.progress_label.setText(f"Найдено {len(discrepancies)} несоответствий")

    def _populate_table(self, table_name: str, items: List[FileDiscrepancy]):
        """Заполнить таблицу"""
        table = self._get_table(table_name)
        label = self._get_count_label(table_name)

        if not table:
            return

        table.setRowCount(len(items))

        for row, item in enumerate(items):
            # Чекбокс
            checkbox = QCheckBox()
            checkbox.setProperty("discrepancy", item)
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            table.setCellWidget(row, 0, checkbox_widget)

            # R2 Key
            key_item = QTableWidgetItem(item.r2_key)
            key_item.setToolTip(item.r2_key)
            table.setItem(row, 1, key_item)

            # Тип файла
            file_type = item.file_type or self._guess_file_type(item.r2_key)
            type_item = QTableWidgetItem(file_type)
            table.setItem(row, 2, type_item)

            # Размер R2
            r2_size_str = self._format_size(item.r2_size) if item.r2_size is not None else "-"
            r2_size_item = QTableWidgetItem(r2_size_str)
            r2_size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, 3, r2_size_item)

            # Размер БД
            db_size_str = self._format_size(item.db_size) if item.db_size is not None else "-"
            db_size_item = QTableWidgetItem(db_size_str)
            db_size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, 4, db_size_item)

            # Подсветка несовпадения размеров
            if item.discrepancy_type == DiscrepancyType.SIZE_MISMATCH:
                for col in range(5):
                    cell = table.item(row, col)
                    if cell:
                        cell.setBackground(QColor("#fff3cd"))
                        cell.setForeground(QColor("#333333"))

        if label:
            label.setText(f"Записей: {len(items)}")

    def _guess_file_type(self, r2_key: str) -> str:
        """Определить тип файла по расширению"""
        lower_key = r2_key.lower()
        if lower_key.endswith(".pdf"):
            return "pdf"
        elif lower_key.endswith(".json"):
            if "annotation" in lower_key:
                return "annotation"
            elif "result" in lower_key:
                return "result_json"
            return "json"
        elif lower_key.endswith(".md"):
            return "result_md"
        elif lower_key.endswith(".html"):
            return "ocr_html"
        elif lower_key.endswith((".png", ".jpg", ".jpeg")):
            return "image/crop"
        return "unknown"

    def _format_size(self, size_bytes: Optional[int]) -> str:
        """Форматировать размер файла"""
        if size_bytes is None or size_bytes == 0:
            return "0 B"
        elif size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def _get_current_table(self) -> Optional[QTableWidget]:
        """Получить текущую активную таблицу"""
        current_idx = self.tabs.currentIndex()
        if current_idx == 0:
            return self._get_table("orphan_r2")
        elif current_idx == 1:
            return self._get_table("orphan_db")
        else:
            return self._get_table("size_mismatch")

    def _select_all_current_tab(self):
        """Выбрать все в текущей вкладке"""
        table = self._get_current_table()
        if not table:
            return
        for row in range(table.rowCount()):
            widget = table.cellWidget(row, 0)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(True)

    def _deselect_all_current_tab(self):
        """Снять выбор в текущей вкладке"""
        table = self._get_current_table()
        if not table:
            return
        for row in range(table.rowCount()):
            widget = table.cellWidget(row, 0)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)

    def _get_selected_discrepancies(self, table: QTableWidget) -> List[FileDiscrepancy]:
        """Получить выбранные несоответствия из таблицы"""
        selected = []
        for row in range(table.rowCount()):
            widget = table.cellWidget(row, 0)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    discrepancy = checkbox.property("discrepancy")
                    if discrepancy:
                        selected.append(discrepancy)
        return selected

    def _delete_selected_from_r2(self):
        """Удалить выбранные файлы из R2"""
        table = self._get_current_table()
        if not table:
            return

        selected = self._get_selected_discrepancies(table)
        if not selected:
            QMessageBox.information(self, "Информация", "Не выбраны файлы для удаления")
            return

        # Фильтруем только те, что есть в R2
        r2_keys = [d.r2_key for d in selected if d.discrepancy_type in
                   (DiscrepancyType.ORPHAN_R2, DiscrepancyType.SIZE_MISMATCH)]

        if not r2_keys:
            QMessageBox.information(self, "Информация", "Выбранные записи не имеют файлов в R2")
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы уверены, что хотите удалить {len(r2_keys)} файл(ов) из R2?\n\n"
            "Это действие необратимо!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()

            deleted, errors = r2.delete_objects_batch(r2_keys)

            if errors:
                QMessageBox.warning(
                    self,
                    "Частичное удаление",
                    f"Удалено: {len(deleted)}\nОшибок: {len(errors)}"
                )
            else:
                QMessageBox.information(
                    self,
                    "Успешно",
                    f"Удалено {len(deleted)} файл(ов) из R2"
                )

            # Обновляем сверку
            self._start_reconciliation()

        except Exception as e:
            logger.exception(f"Error deleting from R2: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка удаления:\n{e}")

    def _delete_selected_from_db(self):
        """Удалить выбранные записи из Supabase"""
        table = self._get_current_table()
        if not table:
            return

        selected = self._get_selected_discrepancies(table)
        if not selected:
            QMessageBox.information(self, "Информация", "Не выбраны записи для удаления")
            return

        # Фильтруем только те, что есть в БД
        db_items = [d for d in selected if d.db_file_id and d.discrepancy_type in
                    (DiscrepancyType.ORPHAN_DB, DiscrepancyType.SIZE_MISMATCH)]

        if not db_items:
            QMessageBox.information(self, "Информация", "Выбранные записи не имеют ID в БД")
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы уверены, что хотите удалить {len(db_items)} запись(ей) из Supabase?\n\n"
            "Это действие необратимо!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            deleted_count = 0
            errors_count = 0

            for item in db_items:
                if self.client.delete_node_file(item.db_file_id):
                    deleted_count += 1
                else:
                    errors_count += 1

            if errors_count > 0:
                QMessageBox.warning(
                    self,
                    "Частичное удаление",
                    f"Удалено: {deleted_count}\nОшибок: {errors_count}"
                )
            else:
                QMessageBox.information(
                    self,
                    "Успешно",
                    f"Удалено {deleted_count} запись(ей) из Supabase"
                )

            # Обновляем сверку
            self._start_reconciliation()

        except Exception as e:
            logger.exception(f"Error deleting from DB: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка удаления:\n{e}")

    def closeEvent(self, event):
        """Обработать закрытие диалога"""
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        super().closeEvent(event)
