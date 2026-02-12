"""Диалог настройки разделения PDF документа."""
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)


class SplitDocumentDialog(QDialog):
    """Диалог для выбора параметров разделения PDF."""

    def __init__(self, document_name: str, page_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Разделить документ")
        self.setMinimumWidth(400)
        self._page_count = page_count
        self._setup_ui(document_name, page_count)

    def _setup_ui(self, document_name: str, page_count: int):
        layout = QVBoxLayout(self)

        # Информация о документе
        info_label = QLabel(
            f"Документ: {document_name}\nСтраниц: {page_count}"
        )
        layout.addWidget(info_label)

        # Группа настроек
        group = QGroupBox("Параметры разделения")
        group_layout = QVBoxLayout(group)

        # Количество частей
        parts_layout = QHBoxLayout()
        parts_layout.addWidget(QLabel("Количество частей:"))
        self._parts_spin = QSpinBox()
        self._parts_spin.setMinimum(2)
        self._parts_spin.setMaximum(page_count)
        self._parts_spin.setValue(2)
        self._parts_spin.valueChanged.connect(self._update_preview)
        parts_layout.addWidget(self._parts_spin)
        parts_layout.addStretch()
        group_layout.addLayout(parts_layout)

        # Предпросмотр распределения
        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        group_layout.addWidget(self._preview_label)

        layout.addWidget(group)

        # Кнопки
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview(2)

    def _update_preview(self, num_parts: int):
        """Обновить текст предпросмотра распределения страниц."""
        from rd_core.pdf_split import calculate_page_ranges

        try:
            ranges = calculate_page_ranges(self._page_count, num_parts)
        except ValueError:
            self._preview_label.setText("")
            return

        lines = []
        for i, (start, end) in enumerate(ranges):
            count = end - start + 1
            lines.append(
                f"  Часть {i + 1}: стр. {start + 1}\u2013{end + 1} ({count} стр.)"
            )
        self._preview_label.setText("\n".join(lines))

    @property
    def num_parts(self) -> int:
        return self._parts_spin.value()
