"""Диалог создания узла дерева проектов"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
)

from app.gui.project_tree import NODE_TYPE_NAMES, get_node_type_name
from app.tree_client import NodeType, SectionType, StageType


class CreateNodeDialog(QDialog):
    """Диалог создания узла дерева.

    v2: Упрощённая версия - для FOLDER/DOCUMENT просто запрашивает имя.
    Legacy stage_types/section_types поддерживаются для обратной совместимости.
    """

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
        type_name = get_node_type_name(self.node_type)
        self.setWindowTitle(f"Создать: {type_name}")
        self.setMinimumWidth(350)

        layout = QFormLayout(self)

        # v2: Для FOLDER и DOCUMENT просто показываем поле ввода имени
        # Legacy: для STAGE и SECTION с справочниками показываем комбобокс
        raw_type = self.node_type.value if hasattr(self.node_type, 'value') else str(self.node_type)

        if raw_type == "stage" and self.stage_types:
            self.stage_combo = QComboBox()
            for st in self.stage_types:
                self.stage_combo.addItem(f"{st.code} - {st.name}", st)
            layout.addRow("Стадия:", self.stage_combo)
            self.name_edit = None
        elif raw_type == "section" and self.section_types:
            self.section_combo = QComboBox()
            for st in self.section_types:
                self.section_combo.addItem(f"{st.code} - {st.name}", st)
            layout.addRow("Раздел:", self.section_combo)
            self.name_edit = None
        else:
            # v2: Стандартный ввод имени для folder/document
            self.name_edit = QLineEdit()
            placeholder = "Введите название папки..." if self.node_type == NodeType.FOLDER else "Введите название..."
            self.name_edit.setPlaceholderText(placeholder)
            layout.addRow("Название:", self.name_edit)
            self.stage_combo = None
            self.section_combo = None

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> tuple[str, Optional[str]]:
        """Вернуть (name, code)"""
        raw_type = self.node_type.value if hasattr(self.node_type, 'value') else str(self.node_type)

        if raw_type == "stage" and hasattr(self, "stage_combo") and self.stage_combo is not None:
            st = self.stage_combo.currentData()
            if st and hasattr(st, "name") and hasattr(st, "code"):
                return st.name, st.code
            text = self.stage_combo.currentText()
            if " - " in text:
                code, name = text.split(" - ", 1)
                return name, code
            return text, None
        elif raw_type == "section" and hasattr(self, "section_combo") and self.section_combo is not None:
            st = self.section_combo.currentData()
            if st and hasattr(st, "name") and hasattr(st, "code"):
                return st.name, st.code
            text = self.section_combo.currentText()
            if " - " in text:
                code, name = text.split(" - ", 1)
                return name, code
            return text, None
        else:
            return self.name_edit.text().strip(), None
