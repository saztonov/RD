"""Делегаты для отрисовки элементов дерева проектов"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem


class VersionHighlightDelegate(QStyledItemDelegate):
    """Делегат для отображения версии красным цветом"""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        version = index.data(Qt.UserRole + 1)
        if not version:
            super().paint(painter, option, index)
            return

        # Рисуем фон выделения
        self.initStyleOption(option, index)
        painter.save()

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#2a2d2e"))

        text = index.data(Qt.DisplayRole)

        # Разбиваем текст: иконка + остальное
        parts = text.split(" ", 1)
        icon_part = parts[0] + " " if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        x = option.rect.x() + 4
        y = option.rect.y()
        h = option.rect.height()

        fm = painter.fontMetrics()

        # Иконка
        painter.setPen(option.palette.text().color())
        painter.drawText(
            x, y, fm.horizontalAdvance(icon_part), h, Qt.AlignVCenter, icon_part
        )
        x += fm.horizontalAdvance(icon_part)

        # Версия красным
        painter.setPen(QColor("#ff4444"))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        fm_bold = painter.fontMetrics()
        version_with_space = version + "  "  # Два пробела для чёткого разделения
        painter.drawText(
            x,
            y,
            fm_bold.horizontalAdvance(version_with_space),
            h,
            Qt.AlignVCenter,
            version_with_space,
        )
        x += fm_bold.horizontalAdvance(version_with_space)

        # Остальной текст
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(option.palette.text().color())
        painter.drawText(x, y, option.rect.width() - x, h, Qt.AlignVCenter, rest)

        painter.restore()
