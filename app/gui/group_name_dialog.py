"""
Немодальный диалог ввода названия группы
"""
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class GroupNameDialog(QDialog):
    """Немодальный диалог для ввода названия группы"""

    def __init__(self, parent, blocks_data: list, callback):
        super().__init__(parent)
        self.blocks_data = blocks_data
        self.callback = callback

        self.setWindowTitle("Новая группа")
        self.setWindowFlags(
            Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint
        )
        self.setModal(False)
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Введите название группы:"))

        self.name_edit = QLineEdit()
        self.name_edit.returnPressed.connect(self._on_ok)
        layout.addWidget(self.name_edit)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.name_edit.setFocus()

    def _on_ok(self):
        name = self.name_edit.text().strip()
        if name:
            group_id = str(uuid.uuid4())
            self.callback(self.blocks_data, group_id, name)
            self.close()
