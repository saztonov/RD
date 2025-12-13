"""
Боковая панель с заданиями
"""

from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
                               QListWidget, QListWidgetItem, QHBoxLayout,
                               QGroupBox, QMessageBox, QInputDialog, QMenu,
                               QFileDialog, QAbstractItemView, QFrame, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QUrl
from PySide6.QtGui import QFont, QCursor, QIcon, QDesktopServices
from app.gui.project_manager import Project


class ProjectItemWidget(QWidget):
    """Виджет элемента проекта с раскрывающимся списком файлов"""
    
    clicked = Signal(str)  # project_id
    file_selected = Signal(str, int)  # project_id, file_index
    size_changed = Signal()  # Сигнал об изменении размера
    
    def __init__(self, project: Project, is_expanded: bool = False):
        super().__init__()
        self.project = project
        self.is_expanded = is_expanded
        self._file_buttons = []
        self._file_widgets = []
        self._setup_ui()
    
    def _setup_ui(self):
        """Создать UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        
        # --- Заголовок ---
        self.header_frame = QFrame()
        self.header_frame.setCursor(Qt.PointingHandCursor)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(6)
        
        # Стрелка раскрытия
        self.arrow_label = QLabel("▼" if self.is_expanded else "▶")
        self.arrow_label.setFixedSize(12, 12)
        self.arrow_label.setStyleSheet("color: #808080; font-size: 10px;")
        header_layout.addWidget(self.arrow_label)
        
        # Иконка папки
        icon_label = QLabel("📁")
        icon_label.setFixedSize(16, 16)
        header_layout.addWidget(icon_label)
        
        # Название проекта
        self.name_label = QLabel(self.project.name)
        self.name_label.setWordWrap(False)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 10pt; color: #e0e0e0;")
        header_layout.addWidget(self.name_label, stretch=1)
        
        # Счетчик файлов
        self.count_label = QLabel(str(len(self.project.files)) if self.project.files else "")
        self.count_label.setStyleSheet("""
            background-color: #3e3e42; 
            color: #cccccc; 
            border-radius: 8px; 
            padding: 2px 6px;
            font-size: 8pt;
        """)
        self.count_label.setVisible(bool(self.project.files))
        header_layout.addWidget(self.count_label)
        
        layout.addWidget(self.header_frame)
        
        # --- Контейнер файлов ---
        self.files_container = QWidget()
        files_layout = QVBoxLayout(self.files_container)
        files_layout.setContentsMargins(0, 2, 0, 2)
        files_layout.setSpacing(1)
        
        self._rebuild_files_list(files_layout)
        
        self.files_container.setVisible(self.is_expanded)
        layout.addWidget(self.files_container)
        
        # Стиль виджета
        self.setStyleSheet("""
            ProjectItemWidget {
                background-color: #252526;
                border-radius: 4px;
            }
        """)
        self.header_frame.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border-radius: 4px;
            }
            QFrame:hover {
                background-color: #2a2d2e;
            }
        """)
        
        # Событие клика по заголовку
        self.header_frame.mousePressEvent = self._on_header_clicked
    
    def _rebuild_files_list(self, layout: QVBoxLayout = None):
        """Перестроить список файлов"""
        if layout is None:
            layout = self.files_container.layout()
        
        # Очищаем старые кнопки - удаляем виджеты немедленно
        self._file_buttons.clear()
        self._file_widgets.clear()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        
        if self.project.files:
            for i, file in enumerate(self.project.files):
                file_widget = QWidget()
                file_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                
                # Создаём фиксированную ссылку на виджет для контекстного меню
                def make_context_handler(idx, widget):
                    return lambda pos: self._show_file_context_menu(pos, idx, widget)
                
                file_widget.customContextMenuRequested.connect(make_context_handler(i, file_widget))
                
                file_row = QHBoxLayout(file_widget)
                file_row.setContentsMargins(28, 0, 4, 0)
                file_row.setSpacing(4)
                
                file_btn = QPushButton(f"📄 {file.pdf_name}")
                file_btn.setCursor(Qt.PointingHandCursor)
                file_btn.setFixedHeight(26)
                file_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                
                is_active = (i == self.project.active_file_index)
                self._apply_file_button_style(file_btn, is_active)
                
                # Создаём фиксированную функцию для обработки клика
                def make_click_handler(idx, proj_id):
                    return lambda: self.file_selected.emit(proj_id, idx)
                
                file_btn.clicked.connect(make_click_handler(i, self.project.id))
                
                open_dir_btn = QPushButton("📂")
                open_dir_btn.setCursor(Qt.PointingHandCursor)
                open_dir_btn.setToolTip("Открыть папку")
                open_dir_btn.setFixedSize(26, 26)
                open_dir_btn.setStyleSheet("""
                    QPushButton {
                        border: none;
                        background-color: transparent;
                        color: #cccccc;
                        border-radius: 3px;
                    }
                    QPushButton:hover {
                        background-color: #2a2d2e;
                        color: white;
                    }
                """)
                open_dir_btn.clicked.connect(lambda checked=False, p=file.pdf_path: self._open_file_folder(p))

                file_row.addWidget(file_btn, stretch=1)
                file_row.addWidget(open_dir_btn)
                layout.addWidget(file_widget)
                self._file_buttons.append((file_btn, i))
                self._file_widgets.append((file_widget, i))
        else:
            empty_label = QLabel("Нет файлов")
            empty_label.setStyleSheet("color: #666; font-style: italic; margin-left: 34px; margin-bottom: 4px;")
            layout.addWidget(empty_label)
        
        # Принудительно обновляем layout
        self.files_container.updateGeometry()
        self.updateGeometry()

    def _open_file_folder(self, file_path: str):
        p = Path(file_path)
        folder = p.parent
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            QMessageBox.warning(self, "Ошибка", f"Папка не найдена:\n{folder}")
    
    def _apply_file_button_style(self, btn: QPushButton, is_active: bool):
        """Применить стиль к кнопке файла"""
        bg_color = "#094771" if is_active else "transparent"
        text_color = "#ffffff" if is_active else "#cccccc"
        font_weight = "bold" if is_active else "normal"
        
        btn.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                border: none;
                background-color: {bg_color};
                color: {text_color};
                font-weight: {font_weight};
                padding-left: 6px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: #2a2d2e;
                color: white;
            }}
        """)
    
    def _on_header_clicked(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_expanded()
            self.clicked.emit(self.project.id)
    
    def toggle_expanded(self):
        """Переключить раскрытие/сворачивание"""
        self.is_expanded = not self.is_expanded
        self.files_container.setVisible(self.is_expanded)
        self.arrow_label.setText("▼" if self.is_expanded else "▶")
        self.size_changed.emit()
    
    def set_expanded(self, expanded: bool):
        """Установить состояние раскрытия"""
        if self.is_expanded != expanded:
            self.is_expanded = expanded
            self.files_container.setVisible(self.is_expanded)
            self.arrow_label.setText("▼" if self.is_expanded else "▶")
            self.size_changed.emit()
    
    def update_project(self, project: Project):
        """Обновить данные проекта без пересоздания UI"""
        old_files_count = len(self._file_buttons)  # Используем реальное кол-во кнопок
        
        self.project = project
        
        # Обновляем название
        self.name_label.setText(project.name)
        
        # Обновляем счетчик
        files_count = len(project.files)
        self.count_label.setText(str(files_count) if files_count else "")
        self.count_label.setVisible(files_count > 0)
        
        # Если количество файлов изменилось - перестраиваем список
        if old_files_count != files_count:
            self._rebuild_files_list()
            # Автоматически раскрываем если добавился файл
            if files_count > old_files_count and not self.is_expanded:
                self.is_expanded = True
                self.files_container.setVisible(True)
                self.arrow_label.setText("▼")
            self.size_changed.emit()
        else:
            # Всегда обновляем стили активности если количество не изменилось
            self._update_file_buttons_styles()
    
    def _update_file_buttons_styles(self):
        """Обновить стили всех кнопок файлов"""
        for btn, idx in self._file_buttons:
            is_active = (idx == self.project.active_file_index)
            self._apply_file_button_style(btn, is_active)
    
    def _show_file_context_menu(self, pos, file_index: int, widget: QWidget):
        """Показать контекстное меню для файла"""
        menu = QMenu(self)
        
        act_move_up = menu.addAction("⬆️ Переместить вверх")
        act_move_up.setEnabled(file_index > 0)
        
        act_move_down = menu.addAction("⬇️ Переместить вниз")
        act_move_down.setEnabled(file_index < len(self.project.files) - 1)
        
        menu.addSeparator()
        act_remove = menu.addAction("🗑️ Удалить файл")
        
        result = menu.exec_(widget.mapToGlobal(pos))
        
        if result == act_move_up:
            self._move_file_up(file_index)
        elif result == act_move_down:
            self._move_file_down(file_index)
        elif result == act_remove:
            reply = QMessageBox.question(
                self, "Подтверждение",
                f"Удалить файл '{self.project.files[file_index].pdf_name}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # Эмитим сигнал для удаления файла
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._emit_file_removed(self.project.id, file_index))
    
    def _emit_file_removed(self, project_id: str, file_index: int):
        """Эмитировать сигнал об удалении файла (через родительский виджет)"""
        # Находим родительский ProjectSidebar и вызываем удаление
        parent = self.parent()
        while parent and not isinstance(parent, ProjectSidebar):
            parent = parent.parent()
        
        if parent:
            parent._remove_file_from_project(project_id, file_index)
    
    def _move_file_up(self, file_index: int):
        """Переместить файл вверх"""
        parent = self.parent()
        while parent and not isinstance(parent, ProjectSidebar):
            parent = parent.parent()
        
        if parent:
            parent._move_file_up_in_project(self.project.id, file_index)
    
    def _move_file_down(self, file_index: int):
        """Переместить файл вниз"""
        parent = self.parent()
        while parent and not isinstance(parent, ProjectSidebar):
            parent = parent.parent()
        
        if parent:
            parent._move_file_down_in_project(self.project.id, file_index)
    
    def sizeHint(self) -> QSize:
        """Правильный расчет размера"""
        # Базовая высота заголовка
        header_height = 38
        
        if self.is_expanded and self.project.files:
            # Высота каждого файла
            files_height = len(self.project.files) * 30 + 8
            total_height = header_height + files_height
        elif self.is_expanded:
            # Пустой раскрытый проект
            total_height = header_height + 28
        else:
            total_height = header_height
        
        return QSize(260, total_height + 8)


class ProjectSidebar(QWidget):
    """Боковая панель с проектами"""
    
    project_switched = Signal(str)  # project_id
    file_switched = Signal(str, int)  # project_id, file_index
    
    def __init__(self, project_manager):
        super().__init__()
        self.project_manager = project_manager
        self._widgets_map = {}  # project_id -> (QListWidgetItem, ProjectItemWidget)
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # --- Верхняя панель ---
        top_panel = QWidget()
        top_panel.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3e3e42;")
        top_layout = QVBoxLayout(top_panel)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(10)
        
        # Заголовок
        header_label = QLabel("ЗАДАНИЯ")
        header_label.setStyleSheet("color: #bbbbbb; font-weight: bold; font-size: 9pt;")
        top_layout.addWidget(header_label)
        
        # Кнопки
        btns_layout = QHBoxLayout()
        btns_layout.setSpacing(8)
        
        self.create_btn = QPushButton("Создать")
        self.create_btn.setCursor(Qt.PointingHandCursor)
        self.create_btn.setStyleSheet("""
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 2px;
            }
            QPushButton:hover { background-color: #1177bb; }
        """)
        self.create_btn.clicked.connect(self._create_project)
        
        self.add_pdf_btn = QPushButton("PDF +")
        self.add_pdf_btn.setCursor(Qt.PointingHandCursor)
        self.add_pdf_btn.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 2px;
            }
            QPushButton:hover { background-color: #4e4e52; }
        """)
        self.add_pdf_btn.clicked.connect(self._add_file_to_active_project)
        
        btns_layout.addWidget(self.create_btn)
        btns_layout.addWidget(self.add_pdf_btn)
        top_layout.addLayout(btns_layout)
        
        layout.addWidget(top_panel)
        
        # --- Список проектов ---
        self.projects_list = QListWidget()
        self.projects_list.setFrameShape(QFrame.NoFrame)
        self.projects_list.setSpacing(4)
        self.projects_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.projects_list.setStyleSheet("""
            QListWidget {
                background-color: #1e1e1e;
                outline: none;
                padding: 4px;
            }
            QListWidget::item {
                background-color: transparent;
                padding: 0px;
                border: none;
            }
            QListWidget::item:hover {
                background-color: transparent;
            }
            QListWidget::item:selected {
                background-color: transparent;
            }
        """)
        self.projects_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.projects_list.customContextMenuRequested.connect(self._show_context_menu)
        
        layout.addWidget(self.projects_list)
    
    def _connect_signals(self):
        self.project_manager.project_added.connect(self._on_project_added)
        self.project_manager.project_updated.connect(self._on_project_updated)
        self.project_manager.project_removed.connect(self._on_project_removed)
    
    def _create_project(self):
        name, ok = QInputDialog.getText(self, "Новое задание", "Название задания:")
        if ok and name.strip():
            pid = self.project_manager.create_project(name.strip())
            self.project_manager.set_active_project(pid)
    
    def _add_file_to_active_project(self):
        active = self.project_manager.get_active_project()
        if not active:
            QMessageBox.warning(self, "Внимание", "Сначала создайте или выберите задание")
            return
        
        paths, _ = QFileDialog.getOpenFileNames(self, "Открыть PDF", "", "PDF Files (*.pdf)")
        if not paths:
            return
        
        # Добавляем все выбранные файлы
        for path in paths:
            self.project_manager.add_file_to_project(active.id, path)
        
        # Получаем обновленный проект
        updated_project = self.project_manager.get_project(active.id)
        if not updated_project:
            return
        
        # Активируем последний добавленный файл
        idx = len(updated_project.files) - 1
        self.project_manager.set_active_file_in_project(active.id, idx)
        
        # Раскрываем проект если свернут
        if active.id in self._widgets_map:
            item, widget = self._widgets_map[active.id]
            widget.set_expanded(True)
            self._update_item_size(item, widget)
        
        # Эмитим сигнал переключения файла
        self.file_switched.emit(active.id, idx)
    
    def _on_project_added(self, pid: str):
        project = self.project_manager.get_project(pid)
        if not project:
            return
        
        item = QListWidgetItem()
        widget = ProjectItemWidget(project, is_expanded=True)
        
        widget.clicked.connect(self._on_project_clicked)
        widget.file_selected.connect(self._on_file_selected)
        widget.size_changed.connect(lambda: self._on_widget_size_changed(pid))
        
        # Устанавливаем размер
        item.setSizeHint(widget.sizeHint())
        
        self.projects_list.addItem(item)
        self.projects_list.setItemWidget(item, widget)
        
        # Сохраняем в карту
        self._widgets_map[pid] = (item, widget)
        
        # Прокручиваем к новому элементу
        self.projects_list.scrollToItem(item)
    
    def _on_project_updated(self, pid: str):
        if pid not in self._widgets_map:
            return
        
        project = self.project_manager.get_project(pid)
        if not project:
            return
        
        item, widget = self._widgets_map[pid]
        widget.update_project(project)
        self._update_item_size(item, widget)
    
    def _on_project_removed(self, pid: str):
        if pid not in self._widgets_map:
            return
        
        item, widget = self._widgets_map[pid]
        
        # Находим индекс и удаляем
        for i in range(self.projects_list.count()):
            if self.projects_list.item(i) == item:
                self.projects_list.takeItem(i)
                break
        
        del self._widgets_map[pid]
    
    def _on_widget_size_changed(self, pid: str):
        """Обработка изменения размера виджета"""
        if pid in self._widgets_map:
            item, widget = self._widgets_map[pid]
            self._update_item_size(item, widget)
    
    def _update_item_size(self, item: QListWidgetItem, widget: ProjectItemWidget):
        """Обновить размер элемента списка"""
        # Используем отложенное обновление для корректного расчета размера
        QTimer.singleShot(10, lambda: self._do_update_size(item, widget))
    
    def _do_update_size(self, item: QListWidgetItem, widget: ProjectItemWidget):
        """Фактическое обновление размера"""
        # Пересчитываем геометрию виджета
        widget.adjustSize()
        new_size = widget.sizeHint()
        
        # Устанавливаем новый размер
        item.setSizeHint(new_size)
        
        # Форсируем полную перерисовку списка
        self.projects_list.doItemsLayout()
        self.projects_list.update()
    
    def _on_project_clicked(self, pid: str):
        self.project_manager.set_active_project(pid)
        self.project_switched.emit(pid)
    
    def _on_file_selected(self, pid: str, idx: int):
        self.project_manager.set_active_project(pid)
        self.project_manager.set_active_file_in_project(pid, idx)
        self.file_switched.emit(pid, idx)
    
    def _remove_file_from_project(self, pid: str, file_index: int):
        """Удалить файл из проекта"""
        self.project_manager.remove_file_from_project(pid, file_index)
    
    def _move_file_up_in_project(self, pid: str, file_index: int):
        """Переместить файл вверх в проекте"""
        self.project_manager.move_file_up_in_project(pid, file_index)
    
    def _move_file_down_in_project(self, pid: str, file_index: int):
        """Переместить файл вниз в проекте"""
        self.project_manager.move_file_down_in_project(pid, file_index)
    
    def _show_context_menu(self, pos):
        item = self.projects_list.itemAt(pos)
        if not item:
            return
        
        # Находим виджет по item
        widget = None
        for pid, (it, w) in self._widgets_map.items():
            if it == item:
                widget = w
                break
        
        if not widget:
            return
        
        menu = QMenu(self)
        act_del = menu.addAction("🗑️ Удалить задание")
        act_ren = menu.addAction("✏️ Переименовать")
        
        res = menu.exec_(self.projects_list.mapToGlobal(pos))
        
        if res == act_del:
            reply = QMessageBox.question(
                self, "Подтверждение", 
                f"Удалить '{widget.project.name}'?", 
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.project_manager.remove_project(widget.project.id)
        elif res == act_ren:
            new_name, ok = QInputDialog.getText(
                self, "Переименовать", 
                "Новое имя:", 
                text=widget.project.name
            )
            if ok and new_name.strip():
                widget.project.name = new_name.strip()
                self.project_manager.project_updated.emit(widget.project.id)
