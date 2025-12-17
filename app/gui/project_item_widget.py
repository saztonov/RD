"""Виджет элемента проекта"""

from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
                               QHBoxLayout, QMenu, QMessageBox, QFrame, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QUrl
from PySide6.QtGui import QDesktopServices


class ProjectItemWidget(QWidget):
    """Виджет элемента проекта с раскрывающимся списком файлов"""
    
    clicked = Signal(str)  # project_id
    file_selected = Signal(str, int)  # project_id, file_index
    size_changed = Signal()  # Сигнал об изменении размера
    
    def __init__(self, project, is_expanded: bool = False):
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
    
    def update_project(self, project):
        """Обновить данные проекта без пересоздания UI"""
        old_files_count = len(self._file_buttons)
        
        self.project = project
        
        self.name_label.setText(project.name)
        
        files_count = len(project.files)
        self.count_label.setText(str(files_count) if files_count else "")
        self.count_label.setVisible(files_count > 0)
        
        if old_files_count != files_count:
            self._rebuild_files_list()
            if files_count > old_files_count and not self.is_expanded:
                self.is_expanded = True
                self.files_container.setVisible(True)
                self.arrow_label.setText("▼")
            self.size_changed.emit()
        else:
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
                QTimer.singleShot(0, lambda: self._emit_file_removed(self.project.id, file_index))
    
    def _emit_file_removed(self, project_id: str, file_index: int):
        """Эмитировать сигнал об удалении файла"""
        from app.gui.project_sidebar import ProjectSidebar
        parent = self.parent()
        while parent and not isinstance(parent, ProjectSidebar):
            parent = parent.parent()
        
        if parent:
            parent._remove_file_from_project(project_id, file_index)
    
    def _move_file_up(self, file_index: int):
        """Переместить файл вверх"""
        from app.gui.project_sidebar import ProjectSidebar
        parent = self.parent()
        while parent and not isinstance(parent, ProjectSidebar):
            parent = parent.parent()
        
        if parent:
            parent._move_file_up_in_project(self.project.id, file_index)
    
    def _move_file_down(self, file_index: int):
        """Переместить файл вниз"""
        from app.gui.project_sidebar import ProjectSidebar
        parent = self.parent()
        while parent and not isinstance(parent, ProjectSidebar):
            parent = parent.parent()
        
        if parent:
            parent._move_file_down_in_project(self.project.id, file_index)
    
    def sizeHint(self) -> QSize:
        """Правильный расчет размера"""
        header_height = 38
        
        if self.is_expanded and self.project.files:
            files_height = len(self.project.files) * 30 + 8
            total_height = header_height + files_height
        elif self.is_expanded:
            total_height = header_height + 28
        else:
            total_height = header_height
        
        return QSize(260, total_height + 8)

