"""
Миксин для настройки меню и тулбара
"""

from PySide6.QtWidgets import QToolBar, QLabel, QSpinBox
from PySide6.QtGui import QAction, QKeySequence, QActionGroup
from PySide6.QtCore import Qt
from rd_core.models import BlockType, ShapeType


class MenuSetupMixin:
    """Миксин для создания меню и тулбара"""
    
    def _setup_menu(self):
        """Настройка меню"""
        menubar = self.menuBar()
        
        # Меню "Файл"
        file_menu = menubar.addMenu("&Файл")
        
        open_action = QAction("&Открыть PDF", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_pdf)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        save_action = QAction("&Сохранить разметку", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._save_annotation)
        file_menu.addAction(save_action)
        
        load_action = QAction("&Загрузить разметку", self)
        load_action.setShortcut(QKeySequence("Ctrl+L"))
        load_action.triggered.connect(self._load_annotation)
        file_menu.addAction(load_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("&Выход", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Меню "Инструменты"
        tools_menu = menubar.addMenu("&Инструменты")
        
        sync_r2_action = QAction("🔄 Синхронизация из R2", self)
        sync_r2_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        sync_r2_action.triggered.connect(self._sync_from_r2)
        tools_menu.addAction(sync_r2_action)
        
        tools_menu.addSeparator()
        
        # Remote OCR
        remote_ocr_action = QAction("☁️ Remote OCR (выделенные блоки)", self)
        remote_ocr_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        remote_ocr_action.triggered.connect(self._send_to_remote_ocr)
        tools_menu.addAction(remote_ocr_action)
        
        toggle_remote_panel_action = QAction("📋 Показать панель Remote OCR", self)
        toggle_remote_panel_action.triggered.connect(self._toggle_remote_ocr_panel)
        tools_menu.addAction(toggle_remote_panel_action)
        
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
    
    def _setup_toolbar(self):
        """Настройка панели инструментов"""
        toolbar = QToolBar("Основная панель")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Кнопки навигации
        self.open_action = QAction("📂 Открыть", self)
        self.open_action.triggered.connect(self._open_pdf)
        toolbar.addAction(self.open_action)
        
        self.save_action = QAction("💾 Сохранить", self)
        self.save_action.triggered.connect(self._save_annotation)
        toolbar.addAction(self.save_action)
        
        self.load_action = QAction("📥 Загрузить", self)
        self.load_action.triggered.connect(self._load_annotation)
        toolbar.addAction(self.load_action)
        
        toolbar.addSeparator()
        
        # Навигация по страницам
        self.prev_action = QAction("◀ Назад", self)
        self.prev_action.triggered.connect(self._prev_page)
        toolbar.addAction(self.prev_action)
        
        self.page_label = QLabel("Страница: 0 / 0")
        toolbar.addWidget(self.page_label)
        
        # Поле ввода номера страницы
        self.page_input = QSpinBox(self)
        self.page_input.setMinimum(1)
        self.page_input.setMaximum(1)
        self.page_input.setFixedSize(50, 24)
        self.page_input.setEnabled(False)
        self.page_input.setAlignment(Qt.AlignCenter)
        self.page_input.setButtonSymbols(QSpinBox.NoButtons)
        self.page_input.setToolTip("Введите номер страницы и нажмите Enter")
        self.page_input.setStyleSheet("""
            QSpinBox {
                padding: 2px;
                border: none;
                border-bottom: 2px solid #666;
                border-radius: 0px;
                background: transparent;
                font-size: 12px;
                font-weight: 500;
            }
            QSpinBox:hover {
                border-bottom: 2px solid #0078d4;
            }
            QSpinBox:focus {
                border-bottom: 2px solid #0078d4;
                background: rgba(0, 120, 212, 0.05);
            }
            QSpinBox:disabled {
                border-bottom: 2px solid #ccc;
                color: #999;
            }
        """)
        self.page_input.valueChanged.connect(self._goto_page_from_input)
        toolbar.addWidget(self.page_input)
        
        self.next_action = QAction("Вперед ▶", self)
        self.next_action.triggered.connect(self._next_page)
        toolbar.addAction(self.next_action)
        
        toolbar.addSeparator()
        
        # Выбор типа блока для рисования
        toolbar.addWidget(QLabel("  Тип блока:"))
        
        self.block_type_group = QActionGroup(self)
        self.block_type_group.setExclusive(True)
        
        self.text_action = QAction("📝 Текст", self)
        self.text_action.setCheckable(True)
        self.text_action.setChecked(True)
        self.text_action.setData(BlockType.TEXT)
        self.block_type_group.addAction(self.text_action)
        toolbar.addAction(self.text_action)
        
        self.table_action = QAction("📊 Таблица", self)
        self.table_action.setCheckable(True)
        self.table_action.setData(BlockType.TABLE)
        self.block_type_group.addAction(self.table_action)
        toolbar.addAction(self.table_action)
        
        self.image_action = QAction("🖼️ Картинка", self)
        self.image_action.setCheckable(True)
        self.image_action.setData(BlockType.IMAGE)
        self.block_type_group.addAction(self.image_action)
        toolbar.addAction(self.image_action)
        
        toolbar.addSeparator()
        
        # Выбор формы блока
        toolbar.addWidget(QLabel("  Форма:"))
        
        self.shape_type_group = QActionGroup(self)
        self.shape_type_group.setExclusive(True)
        
        self.rectangle_action = QAction("⬛ Прямоугольник", self)
        self.rectangle_action.setCheckable(True)
        self.rectangle_action.setChecked(True)
        self.rectangle_action.setData(ShapeType.RECTANGLE)
        self.shape_type_group.addAction(self.rectangle_action)
        toolbar.addAction(self.rectangle_action)
        
        self.polygon_action = QAction("🔷 Обводка", self)
        self.polygon_action.setCheckable(True)
        self.polygon_action.setData(ShapeType.POLYGON)
        self.polygon_action.setToolTip("Режим полигонов: клик для добавления точки, двойной клик для завершения")
        self.shape_type_group.addAction(self.polygon_action)
        toolbar.addAction(self.polygon_action)
        
        # Коннекты для отслеживания изменений
        self.shape_type_group.triggered.connect(self._on_shape_type_changed)
        
        # Текущий выбранный тип
        self.selected_block_type = BlockType.TEXT
        self.selected_shape_type = ShapeType.RECTANGLE
    
    def _on_shape_type_changed(self, action):
        """Обработка изменения типа формы"""
        shape_type = action.data()
        if shape_type:
            self.selected_shape_type = shape_type

