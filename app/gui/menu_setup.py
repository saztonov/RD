"""
Миксин для настройки меню и тулбара
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QLabel, QSpinBox, QToolBar

from rd_core.models import BlockType, ShapeType


class MenuSetupMixin:
    """Миксин для создания меню и тулбара"""

    def _setup_menu(self):
        """Настройка меню"""
        menubar = self.menuBar()

        # Меню "Файл"
        file_menu = menubar.addMenu("&Файл")

        exit_action = QAction("&Выход", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Меню "Вид"
        view_menu = menubar.addMenu("&Вид")

        zoom_in_action = QAction("Увеличить", self)
        zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        zoom_in_action.triggered.connect(self._zoom_in)
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("Уменьшить", self)
        zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        zoom_out_action.triggered.connect(self._zoom_out)
        view_menu.addAction(zoom_out_action)

        zoom_reset_action = QAction("Сбросить масштаб", self)
        zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        zoom_reset_action.triggered.connect(self._zoom_reset)
        view_menu.addAction(zoom_reset_action)

        fit_action = QAction("Подогнать к окну", self)
        fit_action.setShortcut(QKeySequence("Ctrl+F"))
        fit_action.triggered.connect(self._fit_to_view)
        view_menu.addAction(fit_action)

        view_menu.addSeparator()

        clear_page_action = QAction("Очистить разметку страницы", self)
        clear_page_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        clear_page_action.triggered.connect(self._clear_current_page)
        view_menu.addAction(clear_page_action)

        view_menu.addSeparator()

        # Подменю "Панели"
        panels_menu = view_menu.addMenu("📋 Панели")

        # Меню "Настройки"
        settings_menu = menubar.addMenu("&Настройки")

        folder_settings_action = QAction("📁 Настройка папок", self)
        folder_settings_action.triggered.connect(self._show_folder_settings)
        settings_menu.addAction(folder_settings_action)

        tree_settings_action = QAction("🌳 Настройка дерева проектов", self)
        tree_settings_action.triggered.connect(self._show_tree_settings)
        settings_menu.addAction(tree_settings_action)

        version_settings_action = QAction("📌 Версионность", self)
        version_settings_action.triggered.connect(self._show_version_settings)
        settings_menu.addAction(version_settings_action)

        settings_menu.addSeparator()

        # Настройка категорий изображений
        image_categories_action = QAction("🖼️ Настройка категорий изображений", self)
        image_categories_action.triggered.connect(self._show_image_categories)
        settings_menu.addAction(image_categories_action)

        settings_menu.addSeparator()

        ocr_settings_action = QAction("⚙️ Настройки OCR сервера", self)
        ocr_settings_action.triggered.connect(self._show_ocr_settings)
        settings_menu.addAction(ocr_settings_action)

        settings_menu.addSeparator()

        hotkeys_action = QAction("⌨️ Горячие клавиши", self)
        hotkeys_action.triggered.connect(self._show_hotkeys_dialog)
        settings_menu.addAction(hotkeys_action)

    def _setup_toolbar(self):
        """Настройка панели инструментов"""
        toolbar = QToolBar("Основная панель")
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Навигация по страницам - компактный современный виджет
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

        nav_widget = QWidget()
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setContentsMargins(4, 2, 4, 2)
        nav_layout.setSpacing(2)

        nav_style = """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 14px;
                font-weight: 600;
                color: #888;
            }
            QPushButton:hover {
                background: rgba(100, 100, 100, 0.15);
                color: #fff;
            }
            QPushButton:pressed {
                background: rgba(100, 100, 100, 0.25);
            }
            QPushButton:disabled {
                color: #444;
            }
        """

        self.prev_btn = QPushButton("❮")
        self.prev_btn.setFixedSize(32, 28)
        self.prev_btn.setToolTip("Предыдущая страница (←)")
        self.prev_btn.setStyleSheet(nav_style)
        self.prev_btn.clicked.connect(self._prev_page)
        nav_layout.addWidget(self.prev_btn)

        # Поле ввода номера страницы
        self.page_input = QSpinBox(self)
        self.page_input.setMinimum(1)
        self.page_input.setMaximum(1)
        self.page_input.setFixedSize(48, 28)
        self.page_input.setEnabled(False)
        self.page_input.setAlignment(Qt.AlignCenter)
        self.page_input.setButtonSymbols(QSpinBox.NoButtons)
        self.page_input.setToolTip("Введите номер страницы")
        self.page_input.setStyleSheet(
            """
            QSpinBox {
                padding: 2px;
                border: 1px solid #555;
                border-radius: 4px;
                background: rgba(50, 50, 50, 0.5);
                font-size: 13px;
                font-weight: 600;
                color: #ddd;
            }
            QSpinBox:hover {
                border: 1px solid #777;
                background: rgba(60, 60, 60, 0.6);
            }
            QSpinBox:focus {
                border: 1px solid #0078d4;
                background: rgba(0, 120, 212, 0.1);
            }
            QSpinBox:disabled {
                border: 1px solid #444;
                color: #666;
                background: rgba(40, 40, 40, 0.3);
            }
        """
        )
        self.page_input.valueChanged.connect(self._goto_page_from_input)
        nav_layout.addWidget(self.page_input)

        self.page_label = QLabel("/ 0")
        self.page_label.setStyleSheet(
            "color: #888; font-size: 13px; font-weight: 500; padding: 0 4px;"
        )
        nav_layout.addWidget(self.page_label)

        self.next_btn = QPushButton("❯")
        self.next_btn.setFixedSize(32, 28)
        self.next_btn.setToolTip("Следующая страница (→)")
        self.next_btn.setStyleSheet(nav_style)
        self.next_btn.clicked.connect(self._next_page)
        nav_layout.addWidget(self.next_btn)

        toolbar.addWidget(nav_widget)

        toolbar.addSeparator()

        # Выбор типа блока для рисования
        toolbar.addWidget(QLabel("  Тип блока:"))

        self.block_type_group = QActionGroup(self)
        self.block_type_group.setExclusive(True)

        self.text_action = QAction("📝 Текст", self)
        self.text_action.setCheckable(True)
        self.text_action.setChecked(True)
        self.text_action.setData({"block_type": BlockType.TEXT})
        self.text_action.setToolTip("Режим рисования текстовых блоков (Ctrl+1)")
        self.block_type_group.addAction(self.text_action)
        toolbar.addAction(self.text_action)

        self.image_action = QAction("🖼️ Картинка", self)
        self.image_action.setCheckable(True)
        self.image_action.setData({"block_type": BlockType.IMAGE})
        self.image_action.setToolTip("Режим рисования блоков картинок (Ctrl+2)")
        self.block_type_group.addAction(self.image_action)
        toolbar.addAction(self.image_action)

        self.stamp_action = QAction("🔏 Штамп", self)
        self.stamp_action.setCheckable(True)
        self.stamp_action.setData(
            {"block_type": BlockType.IMAGE, "category_code": "stamp"}
        )
        self.stamp_action.setToolTip("Режим рисования блоков штампов (Ctrl+3)")
        self.block_type_group.addAction(self.stamp_action)
        toolbar.addAction(self.stamp_action)

        toolbar.addSeparator()

        # Выбор формы блока
        toolbar.addWidget(QLabel("  Форма:"))

        self.shape_type_group = QActionGroup(self)
        self.shape_type_group.setExclusive(True)

        self.rectangle_action = QAction("⬛ Прямоугольник", self)
        self.rectangle_action.setCheckable(True)
        self.rectangle_action.setChecked(True)
        self.rectangle_action.setData(ShapeType.RECTANGLE)
        self.rectangle_action.setToolTip("Режим рисования прямоугольников (Ctrl+Q - переключение)")
        self.shape_type_group.addAction(self.rectangle_action)
        toolbar.addAction(self.rectangle_action)

        self.polygon_action = QAction("🔷 Обводка", self)
        self.polygon_action.setCheckable(True)
        self.polygon_action.setData(ShapeType.POLYGON)
        self.polygon_action.setToolTip(
            "Режим полигонов: клик для добавления точки, двойной клик для завершения (Ctrl+Q - переключение)"
        )
        self.shape_type_group.addAction(self.polygon_action)
        toolbar.addAction(self.polygon_action)

        toolbar.addSeparator()

        # Кнопка группировки блоков
        self.group_blocks_btn = QPushButton("📦 Сгруппировать")
        self.group_blocks_btn.setToolTip("Сгруппировать выбранные блоки (Ctrl+G)")
        self.group_blocks_btn.setStyleSheet(
            """
            QPushButton {
                background: rgba(80, 80, 80, 0.3);
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 13px;
                color: #ccc;
            }
            QPushButton:hover {
                background: rgba(100, 100, 100, 0.4);
                border-color: #777;
                color: #fff;
            }
            QPushButton:pressed {
                background: rgba(120, 120, 120, 0.5);
            }
            QPushButton:disabled {
                color: #555;
                border-color: #444;
            }
        """
        )
        self.group_blocks_btn.clicked.connect(self._group_selected_blocks)
        toolbar.addWidget(self.group_blocks_btn)

        # Коннекты для отслеживания изменений
        self.shape_type_group.triggered.connect(self._on_shape_type_changed)

        # Текущий выбранный тип формы
        self.selected_shape_type = ShapeType.RECTANGLE

        # Растягивающийся спейсер
        spacer = QWidget()
        spacer.setSizePolicy(
            spacer.sizePolicy().horizontalPolicy(), spacer.sizePolicy().verticalPolicy()
        )
        from PySide6.QtWidgets import QSizePolicy

        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # Кнопка запуска распознавания — всегда справа в тулбаре
        self.remote_ocr_btn = QPushButton("🚀 Запустить распознавание")
        self.remote_ocr_btn.setMinimumHeight(36)
        self.remote_ocr_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
        """
        )
        self.remote_ocr_btn.clicked.connect(self._send_to_remote_ocr)
        toolbar.addWidget(self.remote_ocr_btn)

    def _on_shape_type_changed(self, action):
        """Обработка изменения типа формы"""
        shape_type = action.data()
        if shape_type:
            self.selected_shape_type = shape_type
