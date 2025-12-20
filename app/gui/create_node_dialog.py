"""Диалог создания узла дерева проектов"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QDialogButtonBox
)

from app.tree_client import NodeType, StageType, SectionType


NODE_TYPE_NAMES = {
    NodeType.PROJECT: "Проект",
    NodeType.STAGE: "Стадия",
    NodeType.SECTION: "Раздел",
    NodeType.TASK_FOLDER: "Папка заданий",
    NodeType.DOCUMENT: "Документ",
}


class CreateNodeDialog(QDialog):
    """Диалог создания узла дерева"""
    
    def __init__(
        self,
        parent,
        node_type: NodeType,
        stage_types: List[StageType] = None,
        section_types: List[SectionType] = None,
    ):
        super().__init__(parent)
        self.node_type = node_type
        self.stage_types = stage_types or []
        self.section_types = section_types or []
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWindowTitle(f"Создать: {NODE_TYPE_NAMES[self.node_type]}")
        self.setMinimumWidth(350)
        
        layout = QFormLayout(self)
        
        if self.node_type == NodeType.STAGE and self.stage_types:
            self.stage_combo = QComboBox()
            for st in self.stage_types:
                self.stage_combo.addItem(f"{st.code} - {st.name}", st)
            layout.addRow("Стадия:", self.stage_combo)
            self.name_edit = None
        elif self.node_type == NodeType.SECTION and self.section_types:
            self.section_combo = QComboBox()
            for st in self.section_types:
                self.section_combo.addItem(f"{st.code} - {st.name}", st)
            layout.addRow("Раздел:", self.section_combo)
            self.name_edit = None
        else:
            self.name_edit = QLineEdit()
            self.name_edit.setPlaceholderText("Введите название...")
            layout.addRow("Название:", self.name_edit)
            self.stage_combo = None
            self.section_combo = None
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def get_data(self) -> tuple[str, Optional[str]]:
        """Вернуть (name, code)"""
        if self.node_type == NodeType.STAGE and hasattr(self, 'stage_combo') and self.stage_combo is not None:
            st = self.stage_combo.currentData()
            if st and hasattr(st, 'name') and hasattr(st, 'code'):
                return st.name, st.code
            text = self.stage_combo.currentText()
            if " - " in text:
                code, name = text.split(" - ", 1)
                return name, code
            return text, None
        elif self.node_type == NodeType.SECTION and hasattr(self, 'section_combo') and self.section_combo is not None:
            st = self.section_combo.currentData()
            if st and hasattr(st, 'name') and hasattr(st, 'code'):
                return st.name, st.code
            text = self.section_combo.currentText()
            if " - " in text:
                code, name = text.split(" - ", 1)
                return name, code
            return text, None
        else:
            return self.name_edit.text().strip(), None

