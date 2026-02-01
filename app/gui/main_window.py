"""
Главное окно приложения
Интеграция компонентов через миксины
"""

import copy
import logging
from typing import Optional

logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QMainWindow, QProgressBar, QStatusBar

from app.gui.block_handlers import BlockHandlersMixin
from app.gui.blocks_tree_manager import BlocksTreeManager
from app.gui.file_operations import FileOperationsMixin
from app.gui.menu_setup import MenuSetupMixin
from app.gui.navigation_manager import NavigationManager
from app.gui.panels_setup import PanelsSetupMixin
from app.gui.remote_ocr.panel import RemoteOCRPanel
from rd_core.models import BlockType, Document
from rd_core.pdf_utils import PDFDocument

# Импорт метаданных продукта
try:
    from _metadata import __product__, get_version_info
except ImportError:
    __product__ = "Core Structure"

    def get_version_info():
        return "Core Structure v0.1"


class MainWindow(
    MenuSetupMixin,
    PanelsSetupMixin,
    FileOperationsMixin,
    BlockHandlersMixin,
    QMainWindow,
):
    """Главное окно приложения для аннотирования PDF"""

    def __init__(self):
        super().__init__()

        # Данные приложения
        self.pdf_document: Optional[PDFDocument] = None
        self.annotation_document: Optional[Document] = None
        self.current_page: int = 0
        self.page_images: dict = {}
        self._page_images_order: list = []  # LRU порядок страниц
        self._page_images_max: int = 5  # Максимум страниц в кеше
        self.page_zoom_states: dict = {}
        self._current_pdf_path: Optional[str] = None
        self._current_node_id: Optional[str] = None
        self._current_node_locked: bool = False

        # Undo/Redo стек
        self.undo_stack: list = []  # [(page_num, blocks_copy), ...]
        self.redo_stack: list = []
        
        # Буфер обмена для блоков
        self._blocks_clipboard: list = []

        # Менеджеры (инициализируются после setup_ui)
        self.blocks_tree_manager = None
        self.navigation_manager = None
        self.remote_ocr_panel = None
        self.connection_manager = None

        # Настройка UI
        self._setup_menu()
        self._setup_toolbar()
        self._setup_ui()

        # Remote OCR панель
        self._setup_remote_ocr_panel()

        # Добавляем действия панелей в меню
        self._setup_panels_menu()

        # Инициализация менеджеров после создания UI
        self.blocks_tree_manager = BlocksTreeManager(self, self.blocks_tree)
        self.navigation_manager = NavigationManager(self)

        # Подключаем сигналы кеша аннотаций
        self._setup_annotation_cache_signals()

        self.setWindowTitle(__product__)
        self.resize(1200, 800)

        # Статус-бар для отображения прогресса загрузки
        self._setup_status_bar()

        # Инициализация менеджера соединения (после status bar)
        self._setup_connection_manager()

        # Восстановить настройки окна
        self._restore_settings()

        # Гарантировать видимость Remote OCR панели после восстановления настроек
        if self.remote_ocr_panel:
            self.remote_ocr_panel.show()

        # Загрузить настроенные горячие клавиши
        self._update_hotkeys_from_settings()

    def _render_current_page(self, update_tree: bool = True):
        """Отрендерить текущую страницу"""
        if not self.pdf_document:
            return

        self.navigation_manager.load_page_image(self.current_page)

        if self.current_page in self.page_images:
            self.navigation_manager.restore_zoom()

            current_page_data = self._get_or_create_page(self.current_page)
            self.page_viewer.set_blocks(
                current_page_data.blocks if current_page_data else []
            )

            if update_tree:
                self.blocks_tree_manager.update_blocks_tree()

    def _update_ui(self):
        """Обновить UI элементы"""
        if self.pdf_document:
            self.page_label.setText(f"/ {self.pdf_document.page_count}")
            self.page_input.setEnabled(True)
            self.page_input.setMaximum(self.pdf_document.page_count)
            self.page_input.blockSignals(True)
            self.page_input.setValue(self.current_page + 1)
            self.page_input.blockSignals(False)
        else:
            self.page_label.setText("/ 0")
            self.page_input.setEnabled(False)
            self.page_input.setMaximum(1)

    def _prev_page(self):
        """Предыдущая страница"""
        self.navigation_manager.prev_page()

    def _next_page(self):
        """Следующая страница"""
        self.navigation_manager.next_page()

    def _goto_page_from_input(self, page_num: int):
        """Перейти на страницу из поля ввода (нумерация с 1)"""
        if self.pdf_document:
            self.navigation_manager.go_to_page(page_num - 1)

    def _zoom_in(self):
        """Увеличить масштаб"""
        self.navigation_manager.zoom_in()

    def _zoom_out(self):
        """Уменьшить масштаб"""
        self.navigation_manager.zoom_out()

    def _zoom_reset(self):
        """Сбросить масштаб"""
        self.navigation_manager.zoom_reset()

    def _fit_to_view(self):
        """Подогнать к окну"""
        self.navigation_manager.fit_to_view()

    def _save_undo_state(self):
        """Сохранить текущее состояние блоков для отмены"""
        if not self.annotation_document:
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return

        # Делаем глубокую копию блоков
        blocks_copy = copy.deepcopy(current_page_data.blocks)

        # Добавляем в стек undo
        self.undo_stack.append((self.current_page, blocks_copy))

        # Ограничиваем размер стека (последние 50 операций)
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

        # Очищаем стек redo при новом действии
        self.redo_stack.clear()

    def _undo(self):
        """Отменить последнее действие"""
        if not self.undo_stack:
            return

        if not self.annotation_document:
            return

        # Сохраняем текущее состояние в redo
        current_page_data = self._get_or_create_page(self.current_page)
        if current_page_data:
            blocks_copy = copy.deepcopy(current_page_data.blocks)
            self.redo_stack.append((self.current_page, blocks_copy))

        # Восстанавливаем состояние из undo
        page_num, blocks_copy = self.undo_stack.pop()

        # Переключаемся на нужную страницу если надо
        if page_num != self.current_page:
            self.navigation_manager.save_current_zoom()
            self.current_page = page_num
            self.navigation_manager.load_page_image(self.current_page)
            self.navigation_manager.restore_zoom()

        # Восстанавливаем блоки
        page_data = self._get_or_create_page(page_num)
        if page_data:
            page_data.blocks = copy.deepcopy(blocks_copy)
            self.page_viewer.set_blocks(page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
            self._update_ui()

    def _redo(self):
        """Повторить отменённое действие"""
        if not self.redo_stack:
            return

        if not self.annotation_document:
            return

        # Сохраняем текущее состояние в undo
        current_page_data = self._get_or_create_page(self.current_page)
        if current_page_data:
            blocks_copy = copy.deepcopy(current_page_data.blocks)
            self.undo_stack.append((self.current_page, blocks_copy))

        # Восстанавливаем состояние из redo
        page_num, blocks_copy = self.redo_stack.pop()

        # Переключаемся на нужную страницу если надо
        if page_num != self.current_page:
            self.navigation_manager.save_current_zoom()
            self.current_page = page_num
            self.navigation_manager.load_page_image(self.current_page)
            self.navigation_manager.restore_zoom()

        # Восстанавливаем блоки
        page_data = self._get_or_create_page(page_num)
        if page_data:
            page_data.blocks = copy.deepcopy(blocks_copy)
            self.page_viewer.set_blocks(page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
            self._update_ui()

    def _clear_interface(self):
        """Очистить интерфейс при отсутствии файлов"""
        if self.pdf_document:
            self.pdf_document.close()
        self.pdf_document = None
        self.annotation_document = None
        self._current_pdf_path = None

        # Вернуть логи в папку проектов или дефолтную
        from app.logging_manager import get_logging_manager
        get_logging_manager().switch_to_projects_folder()

        self.page_images.clear()
        self._page_images_order.clear()
        self.page_viewer.set_page_image(None, 0)
        self.page_viewer.set_blocks([])
        if self.blocks_tree_manager:
            self.blocks_tree_manager.update_blocks_tree()
        # Сбросить подсветку документа в дереве
        if hasattr(self, "project_tree_widget"):
            self.project_tree_widget.highlight_document("")
        # Очистить OCR preview
        if hasattr(self, "ocr_preview") and self.ocr_preview:
            self.ocr_preview.clear()
        self._update_ui()

    def _save_settings(self):
        """Сохранить настройки окна"""
        from PySide6.QtCore import QSettings

        settings = QSettings("PDFAnnotationTool", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

    def _restore_settings(self):
        """Восстановить настройки окна"""
        from PySide6.QtCore import QSettings

        settings = QSettings("PDFAnnotationTool", "MainWindow")

        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

        window_state = settings.value("windowState")
        if window_state:
            self.restoreState(window_state)

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        # Принудительно синхронизировать все несохраненные изменения
        from app.gui.annotation_cache import get_annotation_cache
        cache = get_annotation_cache()
        cache.force_sync_all()
        
        self._flush_pending_save()
        self._save_settings()
        event.accept()

    def _setup_panels_menu(self):
        """Добавить действия панелей в меню Вид → Панели"""
        menubar = self.menuBar()
        for action in menubar.actions():
            if action.text() == "&Вид":
                view_menu = action.menu()
                for sub_action in view_menu.actions():
                    if sub_action.menu() and "Панели" in sub_action.text():
                        panels_menu = sub_action.menu()
                        # Добавляем toggle-действия для каждой док-панели
                        panels_menu.addAction(self.project_dock.toggleViewAction())
                        panels_menu.addAction(self.blocks_dock.toggleViewAction())
                        panels_menu.addAction(self.remote_ocr_panel.toggleViewAction())
                        break
                break

    # === Remote OCR ===
    def _setup_remote_ocr_panel(self):
        """Инициализировать панель Remote OCR"""
        from PySide6.QtCore import Qt

        self.remote_ocr_panel = RemoteOCRPanel(self, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.remote_ocr_panel)
        self.resizeDocks([self.remote_ocr_panel], [520], Qt.Horizontal)
        self.remote_ocr_panel.show()  # Всегда показывать при загрузке

    def _toggle_remote_ocr_panel(self):
        """Показать/скрыть панель Remote OCR"""
        if self.remote_ocr_panel:
            if self.remote_ocr_panel.isVisible():
                self.remote_ocr_panel.hide()
            else:
                self.remote_ocr_panel.show()

    def _show_folder_settings(self):
        """Показать диалог настройки папок"""
        from app.gui.folder_settings_dialog import FolderSettingsDialog

        dialog = FolderSettingsDialog(self)
        dialog.exec()

    def _show_tree_settings(self):
        """Показать диалог настройки дерева проектов"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        from app.gui.tree_settings_widget import TreeSettingsWidget

        dialog = QDialog(self)
        dialog.setWindowTitle("Настройка дерева проектов")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(TreeSettingsWidget(dialog))
        dialog.exec()

        # Обновляем справочники в дереве проектов после закрытия диалога
        if hasattr(self, "project_tree_widget"):
            self.project_tree_widget.refresh_types()

    def _show_version_settings(self):
        """Показать диалог настройки версионности"""
        from app.gui.folder_settings_dialog import VersionSettingsDialog

        dialog = VersionSettingsDialog(self)
        dialog.exec()

    def _show_ocr_settings(self):
        """Показать диалог настроек OCR сервера"""
        from app.gui.ocr_settings import OCRSettingsDialog

        dialog = OCRSettingsDialog(self)
        dialog.exec()

    def _show_image_categories(self):
        """Показать диалог настройки категорий изображений"""
        from app.gui.image_categories_dialog import ImageCategoriesDialog

        dialog = ImageCategoriesDialog(self)
        dialog.exec()

    def _show_hotkeys_dialog(self):
        """Показать диалог настройки горячих клавиш"""
        from app.gui.hotkeys_dialog import HotkeysDialog

        dialog = HotkeysDialog(self)
        dialog.exec()

    def _start_r2_reconciliation(self):
        """Запустить сверку R2/Supabase для всех документов"""
        from app.gui.project_tree.reconciliation_manager import get_reconciliation_manager
        from app.tree_client import NodeType

        if not hasattr(self, "project_tree") or not self.project_tree:
            return

        # Собираем все документы из дерева
        documents = []

        def collect_documents(item):
            node = item.data(0, Qt.UserRole)
            if hasattr(node, "node_type") and node.node_type == NodeType.DOCUMENT:
                r2_key = node.attributes.get("r2_key", "")
                if r2_key:
                    documents.append({"node_id": node.id, "r2_key": r2_key})
            for i in range(item.childCount()):
                collect_documents(item.child(i))

        for i in range(self.project_tree.tree.topLevelItemCount()):
            collect_documents(self.project_tree.tree.topLevelItem(i))

        if not documents:
            self._status_label.setText("Нет документов для сверки")
            return

        # Инициализируем менеджер и запускаем сверку
        recon_manager = get_reconciliation_manager(self.project_tree.client)
        recon_manager.reconciliation_started.connect(self._on_reconciliation_started)
        recon_manager.reconciliation_progress.connect(self._on_reconciliation_progress)
        recon_manager.reconciliation_finished.connect(self._on_reconciliation_finished)
        recon_manager.status_changed.connect(self._on_reconciliation_status_changed)

        recon_manager.start_reconciliation(documents)

    def _on_reconciliation_started(self):
        """Обработать начало сверки"""
        self._status_label.setText("Сверка R2/Supabase...")
        self._status_progress.setValue(0)
        self._status_progress.show()
        if hasattr(self, "hide_reconcile_action"):
            self.hide_reconcile_action.setEnabled(False)

    def _on_reconciliation_progress(self, current: int, total: int):
        """Обработать прогресс сверки"""
        self._status_progress.setMaximum(total)
        self._status_progress.setValue(current)
        self._status_label.setText(f"Сверка: {current}/{total}")

    def _on_reconciliation_finished(self):
        """Обработать завершение сверки"""
        self._status_progress.hide()
        self._status_label.setText("Сверка завершена")
        if hasattr(self, "hide_reconcile_action"):
            self.hide_reconcile_action.setEnabled(True)
        # Обновляем дерево для отображения результатов
        if hasattr(self, "project_tree") and self.project_tree:
            self.project_tree._refresh_tree()

    def _on_reconciliation_status_changed(self, node_id: str, status: str):
        """Обработать изменение статуса документа"""
        # Обновление будет при refresh_tree
        pass

    def _hide_reconciliation_status(self):
        """Скрыть результаты сверки"""
        from app.gui.project_tree.reconciliation_manager import get_reconciliation_manager

        try:
            recon_manager = get_reconciliation_manager()
            recon_manager.clear_statuses()
            if hasattr(self, "hide_reconcile_action"):
                self.hide_reconcile_action.setEnabled(False)
            # Обновляем дерево
            if hasattr(self, "project_tree") and self.project_tree:
                self.project_tree._refresh_tree()
            self._status_label.setText("Результаты сверки скрыты")
        except (ValueError, Exception):
            pass

    def _update_hotkeys_from_settings(self):
        """Обновить горячие клавиши из настроек"""
        from app.gui.hotkeys_dialog import HotkeysDialog

        # Обновляем горячие клавиши для действий в тулбаре
        if hasattr(self, "text_action"):
            self.text_action.setShortcut(
                HotkeysDialog.get_hotkey("text_block")
            )
        if hasattr(self, "image_action"):
            self.image_action.setShortcut(
                HotkeysDialog.get_hotkey("image_block")
            )
        if hasattr(self, "stamp_action"):
            self.stamp_action.setShortcut(
                HotkeysDialog.get_hotkey("stamp_block")
            )

    def _send_to_remote_ocr(self):
        """Отправить выделенные блоки на Remote OCR"""
        if self.remote_ocr_panel:
            self.remote_ocr_panel.show()
            self.remote_ocr_panel._create_job()

    # === Status Bar ===
    def _setup_status_bar(self):
        """Создать статус-бар с прогрессом"""
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        # Виджеты для отображения прогресса
        self._status_label = QLabel("")
        self._status_progress = QProgressBar()
        self._status_progress.setMaximumWidth(200)
        self._status_progress.setMaximumHeight(16)
        self._status_progress.setTextVisible(True)
        self._status_progress.hide()

        # Индикатор статуса соединения
        self._connection_status_label = QLabel("⚪ Проверка...")
        self._connection_status_label.setStyleSheet("color: #888; font-size: 9pt;")
        self._connection_status_label.setToolTip("Статус подключения к серверу")

        # Индикатор статуса DeepSeek OCR
        self._deepseek_status_label = QLabel("⚪ DeepSeek")
        self._deepseek_status_label.setStyleSheet("color: #888; font-size: 9pt;")
        self._deepseek_status_label.setToolTip("Проверка DeepSeek OCR...")

        # Индикатор очереди синхронизации
        self._sync_queue_label = QLabel("")
        self._sync_queue_label.setStyleSheet("color: #888; font-size: 9pt;")
        self._sync_queue_label.setToolTip("Операции ожидают синхронизации")
        self._sync_queue_label.hide()

        self._status_bar.addPermanentWidget(self._sync_queue_label)
        self._status_bar.addPermanentWidget(self._deepseek_status_label)
        self._status_bar.addPermanentWidget(self._connection_status_label)
        self._status_bar.addPermanentWidget(self._status_label)
        self._status_bar.addPermanentWidget(self._status_progress)
        
        # Таймер для обновления индикатора очереди
        self._sync_queue_timer = QTimer(self)
        self._sync_queue_timer.timeout.connect(self._update_sync_queue_indicator)
        self._sync_queue_timer.start(2000)  # Каждые 2 секунды

        # Таймер для проверки DeepSeek health
        self._deepseek_health_timer = QTimer(self)
        self._deepseek_health_timer.timeout.connect(self._check_deepseek_health)
        self._deepseek_health_timer.start(30000)  # Каждые 30 секунд
        # Первая проверка сразу при запуске
        QTimer.singleShot(2000, self._check_deepseek_health)

    def show_transfer_progress(self, message: str, current: int = 0, total: int = 0):
        """Показать прогресс загрузки/скачивания"""
        self._status_label.setText(message)
        if total > 0:
            self._status_progress.setMaximum(total)
            self._status_progress.setValue(current)
            self._status_progress.show()
        else:
            self._status_progress.hide()

    def hide_transfer_progress(self):
        """Скрыть прогресс"""
        self._status_label.setText("")
        self._status_progress.hide()
    
    # === Connection Manager ===
    def _setup_connection_manager(self):
        """Инициализировать менеджер соединения"""
        from app.gui.connection_manager import ConnectionManager, ConnectionStatus

        self.connection_manager = ConnectionManager(self)

        # Устанавливаем callback для проверки соединения
        def check_connection() -> bool:
            """Проверить доступность интернета и сервера"""
            import socket
            import httpx

            # 1. Быстрая проверка через Remote OCR сервер
            try:
                if self.remote_ocr_panel:
                    client = self.remote_ocr_panel._get_client()
                    if client and client.health():
                        return True
            except Exception:
                pass

            # 2. Fallback: проверка базового интернета через DNS
            try:
                socket.create_connection(("8.8.8.8", 53), timeout=3)
                return True
            except (socket.timeout, socket.error, OSError):
                pass

            # 3. Fallback: проверка через HTTP
            try:
                with httpx.Client(timeout=3) as client:
                    response = client.get("https://www.google.com/generate_204")
                    return response.status_code == 204
            except Exception:
                pass

            return False

        self.connection_manager.set_check_callback(check_connection)
        
        # Подключаем сигналы
        self.connection_manager.connection_lost.connect(self._on_connection_lost)
        self.connection_manager.connection_restored.connect(self._on_connection_restored)
        self.connection_manager.status_changed.connect(self._on_connection_status_changed)
        
        # Запускаем мониторинг
        self.connection_manager.start_monitoring()
    
    def _on_connection_lost(self):
        """Обработчик потери соединения (вызывается только при переходе из CONNECTED)"""
        from app.gui.toast import show_toast
        logger.warning("Соединение потеряно")
        show_toast(
            self,
            "⚠️ Работа в офлайн режиме. Изменения будут синхронизированы при восстановлении.",
            duration=5000
        )
        # UI обновляется через _on_connection_status_changed

    def _on_connection_restored(self):
        """Обработчик восстановления соединения"""
        from app.gui.toast import show_toast
        from app.gui.sync_queue import get_sync_queue

        logger.info("Соединение восстановлено")
        queue = get_sync_queue()
        pending_count = queue.size()

        if pending_count > 0:
            show_toast(self, f"✅ Онлайн. Синхронизация {pending_count} изменений...", duration=3000)
        else:
            show_toast(self, "✅ Онлайн", duration=2000)

        # UI обновляется через _on_connection_status_changed
        # Запускаем синхронизацию отложенных операций
        self._sync_pending_operations()
    
    def _on_connection_status_changed(self, status):
        """Обработчик изменения статуса соединения"""
        from app.gui.connection_manager import ConnectionStatus

        if status == ConnectionStatus.CHECKING:
            self._connection_status_label.setText("⚪ Проверка...")
            self._connection_status_label.setStyleSheet("color: #888; font-size: 9pt;")
            self._connection_status_label.setToolTip("Проверка подключения...")
        elif status == ConnectionStatus.RECONNECTING:
            self._connection_status_label.setText("🟡 Переподключение...")
            self._connection_status_label.setStyleSheet("color: #ff9800; font-size: 9pt; font-weight: bold;")
            self._connection_status_label.setToolTip("Попытка переподключения...")
        elif status == ConnectionStatus.CONNECTED:
            self._connection_status_label.setText("🟢 Онлайн")
            self._connection_status_label.setStyleSheet("color: #4caf50; font-size: 9pt; font-weight: bold;")
            self._connection_status_label.setToolTip("Подключено к серверу")
        elif status == ConnectionStatus.DISCONNECTED:
            self._connection_status_label.setText("🔴 Офлайн")
            self._connection_status_label.setStyleSheet("color: #f44336; font-size: 9pt; font-weight: bold;")
            self._connection_status_label.setToolTip("Нет подключения. Работа в офлайн режиме.")
    
    def _update_sync_queue_indicator(self):
        """Обновить индикатор очереди синхронизации"""
        from app.gui.sync_queue import get_sync_queue
        
        queue = get_sync_queue()
        queue_size = queue.size()
        
        if queue_size > 0:
            self._sync_queue_label.setText(f"📤 {queue_size}")
            self._sync_queue_label.setStyleSheet("color: #ff9800; font-size: 9pt; font-weight: bold;")
            self._sync_queue_label.setToolTip(f"{queue_size} операций ожидают синхронизации")
            self._sync_queue_label.show()
        else:
            self._sync_queue_label.hide()

    def _check_deepseek_health(self):
        """Проверить доступность DeepSeek OCR API"""
        from PySide6.QtCore import QThread, Signal

        class HealthCheckWorker(QThread):
            finished = Signal(str, bool)  # status, model_loaded

            def run(self):
                import httpx
                try:
                    with httpx.Client(timeout=10) as client:
                        response = client.get(
                            "https://louvred-madie-gigglier.ngrok-free.dev/health",
                            headers={"ngrok-skip-browser-warning": "true"}
                        )
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("status") == "ok":
                                model_loaded = data.get("model_loaded", False)
                                self.finished.emit("ok", model_loaded)
                                return
                        self.finished.emit("error", False)
                except Exception as e:
                    logger.debug(f"DeepSeek health check failed: {e}")
                    self.finished.emit("unavailable", False)

        def update_ui(status: str, model_loaded: bool):
            if status == "ok":
                if model_loaded:
                    self._deepseek_status_label.setText("🟢 DeepSeek")
                    self._deepseek_status_label.setStyleSheet("color: #4caf50; font-size: 9pt; font-weight: bold;")
                    self._deepseek_status_label.setToolTip("DeepSeek OCR доступен (модель загружена)")
                else:
                    self._deepseek_status_label.setText("🟡 DeepSeek")
                    self._deepseek_status_label.setStyleSheet("color: #ff9800; font-size: 9pt; font-weight: bold;")
                    self._deepseek_status_label.setToolTip("DeepSeek OCR доступен (модель загружается)")
            else:
                self._deepseek_status_label.setText("🔴 DeepSeek")
                self._deepseek_status_label.setStyleSheet("color: #f44336; font-size: 9pt; font-weight: bold;")
                self._deepseek_status_label.setToolTip("DeepSeek OCR недоступен")

        # Запускаем проверку в отдельном потоке
        self._deepseek_health_worker = HealthCheckWorker()
        self._deepseek_health_worker.finished.connect(update_ui)
        self._deepseek_health_worker.start()

    def _sync_pending_operations(self):
        """Синхронизировать отложенные операции"""
        from app.gui.sync_queue import get_sync_queue
        
        queue = get_sync_queue()
        if queue.is_empty():
            return
        
        pending = queue.get_pending_operations()
        logger.info(f"Синхронизация {len(pending)} отложенных операций...")
        
        # Синхронизируем операции в фоновом потоке
        from concurrent.futures import ThreadPoolExecutor
        
        def sync_operation(operation):
            try:
                from app.gui.sync_queue import SyncOperationType
                from rd_core.r2_storage import R2Storage
                from pathlib import Path

                if operation.type == SyncOperationType.UPLOAD_FILE:
                    r2 = R2Storage()
                    local_path = operation.local_path
                    r2_key = operation.r2_key
                    content_type = operation.data.get("content_type") if operation.data else None

                    if not Path(local_path).exists():
                        logger.warning(f"Файл не найден для синхронизации: {local_path}")
                        queue.remove_operation(operation.id)
                        return

                    if r2.upload_file(local_path, r2_key, content_type):
                        logger.info(f"Операция синхронизирована: {operation.id}")

                        # Регистрируем файл аннотации в БД
                        if operation.data and operation.data.get("is_annotation") and operation.node_id:
                            self._register_synced_annotation(
                                operation.node_id, r2_key, local_path
                            )

                        queue.remove_operation(operation.id)

                        # Удаляем временный файл если это был временный файл
                        if operation.data and operation.data.get("is_temp"):
                            try:
                                Path(local_path).unlink()
                            except Exception:
                                pass
                    else:
                        queue.mark_failed(operation.id, "Не удалось загрузить файл")

            except Exception as e:
                logger.error(f"Ошибка синхронизации операции {operation.id}: {e}")
                queue.mark_failed(operation.id, str(e))
        
        # Синхронизируем операции параллельно
        with ThreadPoolExecutor(max_workers=3) as executor:
            executor.map(sync_operation, pending)

    def _register_synced_annotation(self, node_id: str, r2_key: str, local_path: str):
        """Зарегистрировать синхронизированную аннотацию в БД"""
        try:
            from pathlib import Path
            from app.tree_client import FileType, TreeClient

            client = TreeClient()
            client.upsert_node_file(
                node_id=node_id,
                file_type=FileType.ANNOTATION,
                r2_key=r2_key,
                file_name=Path(local_path).name,
                file_size=Path(local_path).stat().st_size,
                mime_type="application/json"
            )

            # Обновляем флаг has_annotation
            node = client.get_node(node_id)
            if node and not node.attributes.get("has_annotation"):
                attrs = node.attributes.copy()
                attrs["has_annotation"] = True
                client.update_node(node_id, attributes=attrs)

            logger.info(f"Аннотация зарегистрирована в БД: {node_id}")

        except Exception as e:
            logger.debug(f"Ошибка регистрации аннотации в БД: {e}")
