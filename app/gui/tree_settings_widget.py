"""Виджет настройки справочников дерева проектов"""
from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QInputDialog, QLabel, QGroupBox, QTabWidget
)
from PySide6.QtCore import Qt

from app.tree_client import TreeClient, StageType, SectionType

logger = logging.getLogger(__name__)


class TreeSettingsWidget(QWidget):
    """Виджет для настройки справочников дерева"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = TreeClient()
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
        
        layout.addWidget(tabs)
        
        # Кнопка обновления
        refresh_btn = QPushButton("🔄 Обновить справочники")
        refresh_btn.clicked.connect(self._refresh_all)
        layout.addWidget(refresh_btn)
    
    def _create_stages_tab(self) -> QWidget:
        """Создать вкладку стадий"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Таблица стадий
        self.stages_table = QTableWidget()
        self.stages_table.setColumnCount(3)
        self.stages_table.setHorizontalHeaderLabels(["Код", "Название", "Порядок"])
        self.stages_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
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
        self.sections_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
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
                {"code": code.strip(), "name": name.strip(), "sort_order": self.stages_table.rowCount() + 1}
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
        
        name, ok = QInputDialog.getText(self, "Изменить стадию", "Название:", text=old_name)
        if not ok:
            return
        
        try:
            self._update_sql("stage_types", stage_id, {"code": code.strip(), "name": name.strip()})
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
        
        reply = QMessageBox.question(
            self, "Подтверждение", f"Удалить стадию '{code}'?"
        )
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
                {"code": code.strip(), "name": name.strip(), "sort_order": self.sections_table.rowCount() + 1}
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
        
        name, ok = QInputDialog.getText(self, "Изменить раздел", "Название:", text=old_name)
        if not ok:
            return
        
        try:
            self._update_sql("section_types", section_id, {"code": code.strip(), "name": name.strip()})
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
        
        reply = QMessageBox.question(
            self, "Подтверждение", f"Удалить раздел '{code}'?"
        )
        if reply == QMessageBox.Yes:
            try:
                self._delete_sql("section_types", section_id)
                self._load_sections()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def _execute_sql(self, table: str, data: dict):
        """Вставить запись"""
        import httpx
        url = f"{self.client.supabase_url}/rest/v1/{table}"
        headers = {
            "apikey": self.client.supabase_key,
            "Authorization": f"Bearer {self.client.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, headers=headers, json=data)
            resp.raise_for_status()
    
    def _update_sql(self, table: str, record_id: int, data: dict):
        """Обновить запись"""
        import httpx
        url = f"{self.client.supabase_url}/rest/v1/{table}?id=eq.{record_id}"
        headers = {
            "apikey": self.client.supabase_key,
            "Authorization": f"Bearer {self.client.supabase_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=30) as client:
            resp = client.patch(url, headers=headers, json=data)
            resp.raise_for_status()
    
    def _delete_sql(self, table: str, record_id: int):
        """Удалить запись"""
        import httpx
        url = f"{self.client.supabase_url}/rest/v1/{table}?id=eq.{record_id}"
        headers = {
            "apikey": self.client.supabase_key,
            "Authorization": f"Bearer {self.client.supabase_key}",
        }
        with httpx.Client(timeout=30) as client:
            resp = client.delete(url, headers=headers)
            resp.raise_for_status()

