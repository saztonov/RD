"""Виджет настройки справочников дерева проектов"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from apps.rd_desktop.client_id import get_client_id
from apps.rd_desktop.tree_client import SectionType, StageType, TreeClient, _get_tree_client

logger = logging.getLogger(__name__)

RECENT_CLIENT_IDS_SETTINGS_KEY = "recent_client_ids"


class TreeSettingsWidget(QWidget):
    """Виджет для настройки справочников дерева"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = TreeClient()
        self._client_id = get_client_id()
        self._recent_client_ids: List[str] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Вкладки для стадий и разделов
        tabs = QTabWidget()

        # Вкладка Стадии
        stages_widget = self._create_stages_tab()
        tabs.addTab(stages_widget, "Стадии")

        # Вкладка Разделы
        sections_widget = self._create_sections_tab()
        tabs.addTab(sections_widget, "Разделы")

        # Вкладка Доступ к проектам
        access_widget = self._create_access_tab()
        tabs.addTab(access_widget, "Доступ")

        layout.addWidget(tabs)

        # Кнопка обновления
        refresh_btn = QPushButton("🔄 Обновить справочники")
        refresh_btn.clicked.connect(self._refresh_all)
        layout.addWidget(refresh_btn)

    def _create_access_tab(self) -> QWidget:
        """Создать вкладку доступа к корневым проектам"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        client_row = QHBoxLayout()
        client_row.addWidget(QLabel("Client ID:"))

        self._client_id_combo = QComboBox()
        self._client_id_combo.setEditable(True)
        self._client_id_combo.setInsertPolicy(QComboBox.NoInsert)
        self._client_id_combo.setMinimumWidth(260)
        client_row.addWidget(self._client_id_combo)

        apply_btn = QPushButton("Применить")
        apply_btn.clicked.connect(self._apply_client_id_from_input)
        client_row.addWidget(apply_btn)

        current_btn = QPushButton("Текущий")
        current_btn.clicked.connect(self._use_current_client_id)
        client_row.addWidget(current_btn)

        layout.addLayout(client_row)

        self._access_status_label = QLabel("")
        self._access_status_label.setStyleSheet("color: #888;")
        layout.addWidget(self._access_status_label)

        self._access_table = QTableWidget()
        self._access_table.setColumnCount(4)
        self._access_table.setHorizontalHeaderLabels(
            ["Доступ", "Проект", "Путь", "ID"]
        )
        self._access_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self._access_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self._access_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self._access_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self._access_table)

        btns = QHBoxLayout()

        refresh_btn = QPushButton("?? Обновить")
        refresh_btn.clicked.connect(self._load_root_access)
        btns.addWidget(refresh_btn)

        select_all_btn = QPushButton("? Выбрать все")
        select_all_btn.clicked.connect(lambda: self._set_all_access(True))
        btns.addWidget(select_all_btn)

        clear_all_btn = QPushButton("?? Снять все")
        clear_all_btn.clicked.connect(lambda: self._set_all_access(False))
        btns.addWidget(clear_all_btn)

        save_btn = QPushButton("?? Сохранить")
        save_btn.clicked.connect(self._save_root_access)
        btns.addWidget(save_btn)

        reset_btn = QPushButton("?? Сбросить фильтр")
        reset_btn.clicked.connect(self._reset_root_access)
        btns.addWidget(reset_btn)

        layout.addLayout(btns)

        return widget

    def _create_stages_tab(self) -> QWidget:
        """Создать вкладку стадий"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Таблица стадий
        self.stages_table = QTableWidget()
        self.stages_table.setColumnCount(3)
        self.stages_table.setHorizontalHeaderLabels(["Код", "Название", "Порядок"])
        self.stages_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.stages_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.stages_table)

        # Кнопки
        btns = QHBoxLayout()

        add_btn = QPushButton("+ Добавить")
        add_btn.clicked.connect(self._add_stage)
        btns.addWidget(add_btn)

        edit_btn = QPushButton("✏️ Изменить")
        edit_btn.clicked.connect(self._edit_stage)
        btns.addWidget(edit_btn)

        del_btn = QPushButton("🗑️ Удалить")
        del_btn.clicked.connect(self._delete_stage)
        btns.addWidget(del_btn)

        layout.addLayout(btns)

        return widget

    def _create_sections_tab(self) -> QWidget:
        """Создать вкладку разделов"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Таблица разделов
        self.sections_table = QTableWidget()
        self.sections_table.setColumnCount(3)
        self.sections_table.setHorizontalHeaderLabels(["Код", "Название", "Порядок"])
        self.sections_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.sections_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.sections_table)

        # Кнопки
        btns = QHBoxLayout()

        add_btn = QPushButton("+ Добавить")
        add_btn.clicked.connect(self._add_section)
        btns.addWidget(add_btn)

        edit_btn = QPushButton("✏️ Изменить")
        edit_btn.clicked.connect(self._edit_section)
        btns.addWidget(edit_btn)

        del_btn = QPushButton("🗑️ Удалить")
        del_btn.clicked.connect(self._delete_section)
        btns.addWidget(del_btn)

        layout.addLayout(btns)

        return widget

    def showEvent(self, event):
        """При показе виджета загружаем данные"""
        super().showEvent(event)
        self._refresh_all()

    def _refresh_all(self):
        """Обновить все справочники"""
        self._load_stages()
        self._load_sections()
        self._load_recent_client_ids()
        self._load_root_access()

    def _load_stages(self):
        """Загрузить стадии"""
        try:
            stages = self.client.get_stage_types()
            self.stages_table.setRowCount(len(stages))
            for i, st in enumerate(stages):
                self.stages_table.setItem(i, 0, QTableWidgetItem(st.code))
                self.stages_table.setItem(i, 1, QTableWidgetItem(st.name))
                self.stages_table.setItem(i, 2, QTableWidgetItem(str(st.sort_order)))
                # Сохраняем ID в первой ячейке
                self.stages_table.item(i, 0).setData(Qt.UserRole, st.id)
        except Exception as e:
            logger.error(f"Failed to load stages: {e}")

    def _load_sections(self):
        """Загрузить разделы"""
        try:
            sections = self.client.get_section_types()
            self.sections_table.setRowCount(len(sections))
            for i, st in enumerate(sections):
                self.sections_table.setItem(i, 0, QTableWidgetItem(st.code))
                self.sections_table.setItem(i, 1, QTableWidgetItem(st.name))
                self.sections_table.setItem(i, 2, QTableWidgetItem(str(st.sort_order)))
                self.sections_table.item(i, 0).setData(Qt.UserRole, st.id)
        except Exception as e:
            logger.error(f"Failed to load sections: {e}")

    def _load_root_access(self):
        """Загрузить доступ к корневым проектам"""
        try:
            roots = self.client.get_root_nodes(use_client_filter=False)
            access_ids = self.client.get_client_root_ids(self._client_id)

            if access_ids is None:
                access_set = {n.id for n in roots}
                self._access_status_label.setText(
                    f"{self._client_id}: фильтр не задан — показываются все проекты"
                )
            else:
                access_set = set(access_ids)
                self._access_status_label.setText(
                    f"{self._client_id}: фильтр {len(access_set)} из {len(roots)} проектов"
                )

            self._access_table.setRowCount(len(roots))
            for row, node in enumerate(roots):
                check_item = QTableWidgetItem()
                check_item.setFlags(check_item.flags() | Qt.ItemIsUserCheckable)
                check_item.setCheckState(
                    Qt.Checked if node.id in access_set else Qt.Unchecked
                )
                check_item.setData(Qt.UserRole, node.id)

                name_item = QTableWidgetItem(node.name)
                path_value = node.path or (node.parent_id or "root")
                if node.parent_id is None and node.path == node.id:
                    path_value = "root"
                path_item = QTableWidgetItem(path_value)
                id_item = QTableWidgetItem(node.id)

                tooltip = f"id: {node.id}\npath: {node.path or '-'}\nparent_id: {node.parent_id or '-'}"
                name_item.setToolTip(tooltip)
                path_item.setToolTip(tooltip)
                id_item.setToolTip(tooltip)

                self._access_table.setItem(row, 0, check_item)
                self._access_table.setItem(row, 1, name_item)
                self._access_table.setItem(row, 2, path_item)
                self._access_table.setItem(row, 3, id_item)

        except Exception as e:
            logger.error(f"Failed to load root access: {e}")
            self._access_status_label.setText("Ошибка загрузки доступа")

    def _get_client_id_from_input(self) -> Optional[str]:
        """Получить client_id из поля ввода с валидацией"""
        client_id = self._client_id_combo.currentText().strip()
        if not client_id:
            QMessageBox.warning(self, "Ошибка", "client_id не задан")
            return None
        try:
            uuid.UUID(client_id)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Некорректный client_id (ожидается UUID)")
            return None
        return client_id

    def _apply_client_id_from_input(self):
        """Применить client_id из поля ввода"""
        client_id = self._get_client_id_from_input()
        if not client_id:
            return
        self._client_id = client_id
        self._add_recent_client_id(client_id)
        self._load_root_access()

    def _use_current_client_id(self):
        """Подставить текущий client_id приложения"""
        self._client_id = get_client_id()
        self._client_id_combo.setCurrentText(self._client_id)
        self._add_recent_client_id(self._client_id)
        self._load_root_access()

    def _collect_checked_root_ids(self) -> List[str]:
        """Собрать список выбранных корневых проектов"""
        root_ids: List[str] = []
        for row in range(self._access_table.rowCount()):
            item = self._access_table.item(row, 0)
            if not item:
                continue
            if item.checkState() == Qt.Checked:
                root_id = item.data(Qt.UserRole)
                if root_id:
                    root_ids.append(str(root_id))
        return root_ids

    def _set_all_access(self, checked: bool):
        """Выбрать или снять все проекты"""
        for row in range(self._access_table.rowCount()):
            item = self._access_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _save_root_access(self):
        """Сохранить доступ к корневым проектам"""
        client_id = self._get_client_id_from_input()
        if not client_id:
            return
        self._client_id = client_id
        self._add_recent_client_id(client_id)

        root_ids = self._collect_checked_root_ids()
        try:
            self.client.set_client_root_ids(root_ids, self._client_id)
            self._access_status_label.setText(
                f"{self._client_id}: фильтр сохранён, {len(root_ids)} проектов"
            )
            QMessageBox.information(
                self, "Сохранено", "Доступ к проектам сохранён для клиента."
            )
        except Exception as e:
            logger.error(f"Failed to save root access: {e}")
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить доступ:\n{e}"
            )

    def _reset_root_access(self):
        """Сбросить фильтр доступа (показывать все проекты)"""
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Сбросить фильтр? Будут показаны все проекты.",
        )
        if reply != QMessageBox.Yes:
            return

        try:
            client_id = self._get_client_id_from_input()
            if not client_id:
                return
            self._client_id = client_id
            self._add_recent_client_id(client_id)
            self.client.clear_client_root_ids(self._client_id)
            self._load_root_access()
        except Exception as e:
            logger.error(f"Failed to reset root access: {e}")
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сбросить фильтр:\n{e}"
            )

    def _load_recent_client_ids(self):
        """Загрузить список последних client_id из настроек"""
        settings = QSettings("RDApp", "TreeSettings")
        recent = settings.value(RECENT_CLIENT_IDS_SETTINGS_KEY, [])
        if isinstance(recent, str):
            recent = [recent]
        self._recent_client_ids = [cid for cid in recent if cid]

        if self._client_id and self._client_id not in self._recent_client_ids:
            self._recent_client_ids.insert(0, self._client_id)

        self._recent_client_ids = self._recent_client_ids[:15]
        self._client_id_combo.clear()
        self._client_id_combo.addItems(self._recent_client_ids)
        self._client_id_combo.setCurrentText(self._client_id)

    def _save_recent_client_ids(self):
        """Сохранить список последних client_id в настройки"""
        settings = QSettings("RDApp", "TreeSettings")
        settings.setValue(RECENT_CLIENT_IDS_SETTINGS_KEY, self._recent_client_ids)

    def _add_recent_client_id(self, client_id: str):
        """Добавить client_id в список последних"""
        if not client_id:
            return
        if client_id in self._recent_client_ids:
            self._recent_client_ids.remove(client_id)
        self._recent_client_ids.insert(0, client_id)
        self._recent_client_ids = self._recent_client_ids[:15]
        self._save_recent_client_ids()
        self._client_id_combo.clear()
        self._client_id_combo.addItems(self._recent_client_ids)
        self._client_id_combo.setCurrentText(client_id)

    def _add_stage(self):
        """Добавить стадию"""
        code, ok = QInputDialog.getText(self, "Новая стадия", "Код (например ПД):")
        if not ok or not code.strip():
            return

        name, ok = QInputDialog.getText(self, "Новая стадия", "Название:")
        if not ok or not name.strip():
            return

        try:
            self._execute_sql(
                "stage_types",
                {
                    "code": code.strip(),
                    "name": name.strip(),
                    "sort_order": self.stages_table.rowCount() + 1,
                },
            )
            self._load_stages()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _edit_stage(self):
        """Редактировать стадию"""
        row = self.stages_table.currentRow()
        if row < 0:
            return

        stage_id = self.stages_table.item(row, 0).data(Qt.UserRole)
        old_code = self.stages_table.item(row, 0).text()
        old_name = self.stages_table.item(row, 1).text()

        code, ok = QInputDialog.getText(self, "Изменить стадию", "Код:", text=old_code)
        if not ok:
            return

        name, ok = QInputDialog.getText(
            self, "Изменить стадию", "Название:", text=old_name
        )
        if not ok:
            return

        try:
            self._update_sql(
                "stage_types", stage_id, {"code": code.strip(), "name": name.strip()}
            )
            self._load_stages()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _delete_stage(self):
        """Удалить стадию"""
        row = self.stages_table.currentRow()
        if row < 0:
            return

        stage_id = self.stages_table.item(row, 0).data(Qt.UserRole)
        code = self.stages_table.item(row, 0).text()

        reply = QMessageBox.question(self, "Подтверждение", f"Удалить стадию '{code}'?")
        if reply == QMessageBox.Yes:
            try:
                self._delete_sql("stage_types", stage_id)
                self._load_stages()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _add_section(self):
        """Добавить раздел"""
        code, ok = QInputDialog.getText(self, "Новый раздел", "Код (например АР):")
        if not ok or not code.strip():
            return

        name, ok = QInputDialog.getText(self, "Новый раздел", "Название:")
        if not ok or not name.strip():
            return

        try:
            self._execute_sql(
                "section_types",
                {
                    "code": code.strip(),
                    "name": name.strip(),
                    "sort_order": self.sections_table.rowCount() + 1,
                },
            )
            self._load_sections()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _edit_section(self):
        """Редактировать раздел"""
        row = self.sections_table.currentRow()
        if row < 0:
            return

        section_id = self.sections_table.item(row, 0).data(Qt.UserRole)
        old_code = self.sections_table.item(row, 0).text()
        old_name = self.sections_table.item(row, 1).text()

        code, ok = QInputDialog.getText(self, "Изменить раздел", "Код:", text=old_code)
        if not ok:
            return

        name, ok = QInputDialog.getText(
            self, "Изменить раздел", "Название:", text=old_name
        )
        if not ok:
            return

        try:
            self._update_sql(
                "section_types",
                section_id,
                {"code": code.strip(), "name": name.strip()},
            )
            self._load_sections()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _delete_section(self):
        """Удалить раздел"""
        row = self.sections_table.currentRow()
        if row < 0:
            return

        section_id = self.sections_table.item(row, 0).data(Qt.UserRole)
        code = self.sections_table.item(row, 0).text()

        reply = QMessageBox.question(self, "Подтверждение", f"Удалить раздел '{code}'?")
        if reply == QMessageBox.Yes:
            try:
                self._delete_sql("section_types", section_id)
                self._load_sections()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _execute_sql(self, table: str, data: dict):
        """Вставить запись"""
        url = f"{self.client.supabase_url}/rest/v1/{table}"
        headers = {
            "apikey": self.client.supabase_key,
            "Authorization": f"Bearer {self.client.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        client = _get_tree_client()
        resp = client.post(url, headers=headers, json=data, timeout=30.0)
        resp.raise_for_status()

    def _update_sql(self, table: str, record_id: int, data: dict):
        """Обновить запись"""
        url = f"{self.client.supabase_url}/rest/v1/{table}?id=eq.{record_id}"
        headers = {
            "apikey": self.client.supabase_key,
            "Authorization": f"Bearer {self.client.supabase_key}",
            "Content-Type": "application/json",
        }
        client = _get_tree_client()
        resp = client.patch(url, headers=headers, json=data, timeout=30.0)
        resp.raise_for_status()

    def _delete_sql(self, table: str, record_id: int):
        """Удалить запись"""
        url = f"{self.client.supabase_url}/rest/v1/{table}?id=eq.{record_id}"
        headers = {
            "apikey": self.client.supabase_key,
            "Authorization": f"Bearer {self.client.supabase_key}",
        }
        client = _get_tree_client()
        resp = client.delete(url, headers=headers, timeout=30.0)
        resp.raise_for_status()
