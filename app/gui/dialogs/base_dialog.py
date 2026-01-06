"""Базовые классы для диалогов приложения"""
from typing import Optional, Tuple, Union

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class BaseDialog(QDialog):
    """
    Базовый класс для диалогов с общей структурой:
    - Заголовок и настройка окна
    - Стандартные кнопки OK/Cancel
    - Методы для создания групп и layout
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "",
        min_width: int = 400,
        modal: bool = True,
        buttons: QDialogButtonBox.StandardButtons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
    ):
        """
        Args:
            parent: Родительский виджет
            title: Заголовок окна
            min_width: Минимальная ширина
            modal: Модальный режим
            buttons: Стандартные кнопки (Ok, Cancel, etc.)
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(min_width)
        self.setModal(modal)

        self._main_layout = QVBoxLayout(self)
        self._button_box: Optional[QDialogButtonBox] = None
        self._buttons_config = buttons

    def _finalize_ui(self) -> None:
        """
        Вызвать в конце _setup_ui для добавления стандартных кнопок.
        Автоматически добавляет stretch перед кнопками.
        """
        self._main_layout.addStretch()

        if self._buttons_config:
            self._button_box = QDialogButtonBox(self._buttons_config)
            self._button_box.accepted.connect(self._on_accept)
            self._button_box.rejected.connect(self.reject)
            self._main_layout.addWidget(self._button_box)

    def _on_accept(self) -> None:
        """
        Переопределить для валидации перед закрытием.
        По умолчанию просто вызывает accept().
        """
        self.accept()

    def add_group(
        self,
        title: str,
        layout_type: str = "vbox"
    ) -> Tuple[QGroupBox, Union[QVBoxLayout, QHBoxLayout, QFormLayout]]:
        """
        Добавить группу с заданным типом layout.

        Args:
            title: Заголовок группы
            layout_type: "vbox", "hbox" или "form"

        Returns:
            (QGroupBox, layout)
        """
        group = QGroupBox(title)

        if layout_type == "form":
            layout = QFormLayout(group)
        elif layout_type == "hbox":
            layout = QHBoxLayout(group)
        else:
            layout = QVBoxLayout(group)

        self._main_layout.addWidget(group)
        return group, layout

    def add_info_label(
        self,
        text: str,
        style: str = "color: #888; font-size: 10px;"
    ) -> QLabel:
        """
        Добавить информационную метку.

        Args:
            text: Текст метки
            style: CSS стиль

        Returns:
            QLabel
        """
        label = QLabel(text)
        label.setStyleSheet(style)
        label.setWordWrap(True)
        self._main_layout.addWidget(label)
        return label

    def add_widget(self, widget: QWidget) -> None:
        """Добавить виджет в главный layout"""
        self._main_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        """Добавить layout в главный layout"""
        self._main_layout.addLayout(layout)


class BaseSettingsDialog(BaseDialog):
    """
    Базовый класс для диалогов настроек с QSettings.

    Предоставляет:
    - Автоматическую загрузку настроек в __init__
    - Методы для работы с QSettings
    """

    # Переопределить в подклассе
    SETTINGS_ORG = "RDApp"
    SETTINGS_APP = "Settings"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "Настройки",
        min_width: int = 400,
    ):
        super().__init__(parent, title, min_width)
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

    def _load_settings(self) -> None:
        """
        Переопределить для загрузки настроек в UI элементы.
        Вызывается после _setup_ui().
        """
        pass

    def _save_settings(self) -> None:
        """
        Переопределить для сохранения настроек из UI элементов.
        Вызывается в _on_accept() после валидации.
        """
        pass

    def get_setting(self, key: str, default=None):
        """Получить значение настройки"""
        return self._settings.value(key, default)

    def set_setting(self, key: str, value) -> None:
        """Установить значение настройки"""
        self._settings.setValue(key, value)

    def _on_accept(self) -> None:
        """Сохранить настройки и закрыть диалог"""
        if self._validate():
            self._save_settings()
            self.accept()

    def _validate(self) -> bool:
        """
        Переопределить для валидации перед сохранением.

        Returns:
            True если валидация прошла успешно
        """
        return True
