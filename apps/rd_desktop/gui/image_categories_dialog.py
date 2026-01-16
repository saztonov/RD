"""
Диалог настройки категорий изображений
Категории хранятся в Supabase (таблица image_categories)
"""

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ImageCategoriesDialog(QDialog):
    """Диалог управления категориями изображений"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка категорий изображений")
        self.resize(900, 650)

        self._categories: List[Dict[str, Any]] = []
        self._current_category: Optional[Dict[str, Any]] = None
        self._tree_client = None

        self._init_tree_client()
        self._setup_ui()
        self._load_categories()

    def _init_tree_client(self):
        """Инициализация TreeClient"""
        try:
            from apps.rd_desktop.tree_client import TreeClient

            self._tree_client = TreeClient()
            if not self._tree_client.is_available():
                self._tree_client = None
                logger.warning("TreeClient недоступен")
        except Exception as e:
            logger.error(f"Ошибка инициализации TreeClient: {e}")
            self._tree_client = None

    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)

        # Заголовок
        header = QLabel("<b>Категории для IMAGE блоков</b>")
        header.setStyleSheet("font-size: 14px; margin-bottom: 8px;")
        layout.addWidget(header)

        info = QLabel(
            "Каждая категория определяет промпт для извлечения JSON из изображений.\n"
            "Категория 'По умолчанию' применяется к новым IMAGE блокам автоматически."
        )
        info.setStyleSheet("color: #888; font-size: 11px; margin-bottom: 12px;")
        layout.addWidget(info)

        # Основной сплиттер
        splitter = QSplitter(Qt.Horizontal)

        # Левая панель: список категорий
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.categories_list = QListWidget()
        self.categories_list.setMinimumWidth(200)
        self.categories_list.currentItemChanged.connect(self._on_category_selected)
        left_layout.addWidget(self.categories_list)

        # Кнопки управления списком
        list_buttons = QHBoxLayout()

        self.add_btn = QPushButton("➕ Добавить")
        self.add_btn.clicked.connect(self._add_category)
        list_buttons.addWidget(self.add_btn)

        self.delete_btn = QPushButton("🗑️ Удалить")
        self.delete_btn.clicked.connect(self._delete_category)
        self.delete_btn.setEnabled(False)
        list_buttons.addWidget(self.delete_btn)

        left_layout.addLayout(list_buttons)
        splitter.addWidget(left_widget)

        # Правая панель: редактор категории
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Основные поля
        fields_group = QGroupBox("Основные настройки")
        fields_layout = QVBoxLayout(fields_group)

        # Название
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Название:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Например: Чертёж, Схема, Фото")
        name_layout.addWidget(self.name_edit)
        fields_layout.addLayout(name_layout)

        # Код
        code_layout = QHBoxLayout()
        code_layout.addWidget(QLabel("Код (slug):"))
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Например: drawing, schema, photo")
        code_layout.addWidget(self.code_edit)
        fields_layout.addLayout(code_layout)

        # Описание
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("Описание:"))
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Краткое описание категории")
        desc_layout.addWidget(self.desc_edit)
        fields_layout.addLayout(desc_layout)

        # По умолчанию
        self.is_default_check = QCheckBox("Категория по умолчанию")
        self.is_default_check.setToolTip(
            "Эта категория будет применяться к новым IMAGE блокам"
        )
        fields_layout.addWidget(self.is_default_check)

        right_layout.addWidget(fields_group)

        # Панель быстрой вставки переменных
        vars_group = QGroupBox("📝 Вставка переменных (клик → вставка в курсор)")
        vars_layout = QHBoxLayout(vars_group)
        vars_layout.setSpacing(4)

        self._variables = [
            ("{DOC_NAME}", "Имя PDF"),
            ("{PAGE_NUM}", "Стр."),
            ("{BLOCK_ID}", "ID блока"),
            ("{OPERATOR_HINT}", "Подсказка"),
            ("{PDFPLUMBER_TEXT}", "Текст PDF"),
        ]

        var_btn_style = """
            QPushButton {
                background: #3b3b3b;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 8px;
                font-family: Consolas, monospace;
                font-size: 11px;
                color: #7dd3fc;
            }
            QPushButton:hover {
                background: #4b4b4b;
                border-color: #7dd3fc;
            }
            QPushButton:pressed {
                background: #2563eb;
            }
        """

        for var_name, var_desc in self._variables:
            btn = QPushButton(var_name)
            btn.setToolTip(f"{var_desc} — кликните для вставки")
            btn.setStyleSheet(var_btn_style)
            btn.clicked.connect(lambda checked, v=var_name: self._insert_variable(v))
            vars_layout.addWidget(btn)

        vars_layout.addStretch()
        right_layout.addWidget(vars_group)

        # System Prompt
        system_group = QGroupBox("System / Role Prompt")
        system_layout = QVBoxLayout(system_group)

        system_info = QLabel(
            "<i style='color:#888'>Роль и контекст для модели (system message)</i>"
        )
        system_layout.addWidget(system_info)

        self.system_edit = QTextEdit()
        self.system_edit.setPlaceholderText(
            "You are an expert engineer analyzing technical drawings...\n\n"
            "Describe the role, context, and general rules for the model."
        )
        self.system_edit.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
        )
        self.system_edit.setMinimumHeight(120)
        system_layout.addWidget(self.system_edit)

        right_layout.addWidget(system_group)

        # User Prompt
        user_group = QGroupBox("User Input Prompt")
        user_layout = QVBoxLayout(user_group)

        user_info = QLabel(
            "<i style='color:#888'>Инструкция для конкретного блока (user message)</i>"
        )
        user_layout.addWidget(user_info)

        self.user_edit = QTextEdit()
        self.user_edit.setPlaceholderText(
            "Extract the following data from the image and return as JSON:\n"
            "- title: string\n"
            "- dimensions: array\n\n"
            "Operator hint: {OPERATOR_HINT}\n"
            "PDF text: {PDFPLUMBER_TEXT}"
        )
        self.user_edit.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
        )
        self.user_edit.setMinimumHeight(150)
        user_layout.addWidget(self.user_edit)

        right_layout.addWidget(user_group)

        # Кнопка сохранения
        save_btn = QPushButton("💾 Сохранить категорию")
        save_btn.clicked.connect(self._save_current_category)
        save_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """
        )
        right_layout.addWidget(save_btn)

        splitter.addWidget(right_widget)
        splitter.setSizes([250, 650])

        layout.addWidget(splitter)

        # Кнопка закрытия
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)

        # Начальное состояние
        self._set_editor_enabled(False)

    def _set_editor_enabled(self, enabled: bool):
        """Включить/выключить редактор"""
        self.name_edit.setEnabled(enabled)
        self.code_edit.setEnabled(enabled)
        self.desc_edit.setEnabled(enabled)
        self.is_default_check.setEnabled(enabled)
        self.system_edit.setEnabled(enabled)
        self.user_edit.setEnabled(enabled)
        self.delete_btn.setEnabled(enabled)

    def _insert_variable(self, variable: str):
        """Вставить переменную в активное поле ввода (system или user)"""
        # Определяем какое поле имеет фокус
        focused = None
        if self.system_edit.hasFocus():
            focused = self.system_edit
        elif self.user_edit.hasFocus():
            focused = self.user_edit
        else:
            # По умолчанию вставляем в user (чаще используется)
            focused = self.user_edit
            self.user_edit.setFocus()

        # Вставляем переменную в позицию курсора
        cursor = focused.textCursor()
        cursor.insertText(variable)
        focused.setTextCursor(cursor)

    def _load_categories(self):
        """Загрузить категории из Supabase"""
        self.categories_list.clear()
        self._categories = []

        if not self._tree_client:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Supabase недоступен. Проверьте SUPABASE_URL и SUPABASE_KEY в .env",
            )
            return

        try:
            self._categories = self._tree_client.get_image_categories()

            for cat in self._categories:
                item = QListWidgetItem()
                name = cat.get("name", "???")
                if cat.get("is_default"):
                    name = f"⭐ {name}"
                item.setText(name)
                item.setData(Qt.UserRole, cat)
                self.categories_list.addItem(item)

            logger.info(f"Загружено {len(self._categories)} категорий")

        except Exception as e:
            logger.error(f"Ошибка загрузки категорий: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить категории:\n{e}")

    def _on_category_selected(
        self, current: QListWidgetItem, previous: QListWidgetItem
    ):
        """Выбрана категория в списке"""
        if not current:
            self._current_category = None
            self._set_editor_enabled(False)
            return

        self._current_category = current.data(Qt.UserRole)
        self._set_editor_enabled(True)

        # Заполняем поля
        self.name_edit.setText(self._current_category.get("name", ""))
        self.code_edit.setText(self._current_category.get("code", ""))
        self.desc_edit.setText(self._current_category.get("description", "") or "")
        self.is_default_check.setChecked(
            self._current_category.get("is_default", False)
        )
        self.system_edit.setPlainText(self._current_category.get("system_prompt", ""))
        self.user_edit.setPlainText(self._current_category.get("user_prompt", ""))

        # Нельзя удалять default категорию
        is_default = self._current_category.get("is_default", False)
        code = self._current_category.get("code", "")
        self.delete_btn.setEnabled(not is_default and code != "default")

    def _add_category(self):
        """Добавить новую категорию"""
        if not self._tree_client:
            return

        try:
            new_cat = self._tree_client.create_image_category(
                name="Новая категория",
                code=f"category_{len(self._categories) + 1}",
                system_prompt="You are an expert assistant.",
                user_prompt="Analyze this image and return JSON.",
                description="",
                is_default=False,
            )

            # Сохраняем ID новой категории
            new_cat_id = new_cat.get("id") if new_cat else None

            self._load_categories()

            # Выбираем новую категорию
            if new_cat_id:
                for i in range(self.categories_list.count()):
                    item = self.categories_list.item(i)
                    item_data = item.data(Qt.UserRole)
                    if item_data and item_data.get("id") == new_cat_id:
                        self.categories_list.setCurrentItem(item)
                        break

            from apps.rd_desktop.gui.toast import show_toast

            show_toast(self.parent() or self, "Категория создана")

        except Exception as e:
            logger.error(f"Ошибка создания категории: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось создать категорию:\n{e}")

    def _save_current_category(self):
        """Сохранить текущую категорию"""
        if not self._current_category or not self._tree_client:
            return

        name = self.name_edit.text().strip()
        code = self.code_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Ошибка", "Введите название категории")
            return

        if not code:
            QMessageBox.warning(self, "Ошибка", "Введите код категории")
            return

        # Сохраняем ID до перезагрузки списка
        category_id = self._current_category["id"]

        try:
            self._tree_client.update_image_category(
                category_id,
                name=name,
                code=code,
                description=self.desc_edit.text().strip(),
                is_default=self.is_default_check.isChecked(),
                system_prompt=self.system_edit.toPlainText(),
                user_prompt=self.user_edit.toPlainText(),
            )

            self._load_categories()

            # Восстанавливаем выбор
            for i in range(self.categories_list.count()):
                item = self.categories_list.item(i)
                if item.data(Qt.UserRole).get("id") == category_id:
                    self.categories_list.setCurrentItem(item)
                    break

            from apps.rd_desktop.gui.toast import show_toast

            show_toast(self.parent() or self, "Категория сохранена")

        except Exception as e:
            logger.error(f"Ошибка сохранения категории: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить категорию:\n{e}")

    def _delete_category(self):
        """Удалить текущую категорию"""
        if not self._current_category or not self._tree_client:
            return

        if (
            self._current_category.get("is_default")
            or self._current_category.get("code") == "default"
        ):
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить категорию по умолчанию")
            return

        cat_name = self._current_category.get("name", "???")
        cat_id = self._current_category.get("id")

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить категорию '{cat_name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        try:
            self._tree_client.delete_image_category(cat_id)
            self._load_categories()

            from apps.rd_desktop.gui.toast import show_toast

            show_toast(self.parent() or self, "Категория удалена")

        except Exception as e:
            logger.error(f"Ошибка удаления категории: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось удалить категорию:\n{e}")
