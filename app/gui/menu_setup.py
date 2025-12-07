"""
Миксин для настройки меню и тулбара
"""

from PySide6.QtWidgets import QToolBar, QLabel
from PySide6.QtGui import QAction, QKeySequence, QActionGroup
from app.models import BlockType


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
        
        # Surya (Surya + Paddle layout)
        surya_all_action = QAction("&Surya (все стр.)", self)
        surya_all_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        surya_all_action.triggered.connect(self._surya_segment_all_pages)
        tools_menu.addAction(surya_all_action)
        
        surya_action = QAction("S&urya разметка", self)
        surya_action.setShortcut(QKeySequence("Ctrl+U"))
        surya_action.triggered.connect(self._surya_segment_pdf)
        tools_menu.addAction(surya_action)
        
        tools_menu.addSeparator()
        
        # Paddle (PP-StructureV3)
        paddle_all_action = QAction("&Paddle (все стр.)", self)
        paddle_all_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        paddle_all_action.triggered.connect(self._paddle_segment_all_pages)
        tools_menu.addAction(paddle_all_action)
        
        paddle_action = QAction("&Paddle разметка", self)
        paddle_action.setShortcut(QKeySequence("Ctrl+P"))
        paddle_action.triggered.connect(self._paddle_segment_pdf)
        tools_menu.addAction(paddle_action)
        
        tools_menu.addSeparator()
        
        run_ocr_action = QAction("Запустить &OCR", self)
        run_ocr_action.setShortcut(QKeySequence("Ctrl+R"))
        run_ocr_action.triggered.connect(self._run_ocr_all)
        tools_menu.addAction(run_ocr_action)
        
        tools_menu.addSeparator()
        
        export_cat_action = QAction("Экспорт категорий", self)
        export_cat_action.triggered.connect(lambda: self.category_manager.export_categories())
        tools_menu.addAction(export_cat_action)
        
        import_cat_action = QAction("Импорт категорий", self)
        import_cat_action.triggered.connect(lambda: self.category_manager.import_categories())
        tools_menu.addAction(import_cat_action)
        
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
        
        # Текущий выбранный тип
        self.selected_block_type = BlockType.TEXT

