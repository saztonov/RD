"""
Боковая панель с заданиями
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
                               QListWidget, QListWidgetItem, QHBoxLayout,
                               QMessageBox, QInputDialog, QMenu,
                               QFileDialog, QAbstractItemView, QFrame)
from PySide6.QtCore import Qt, Signal, QTimer
from app.gui.project_manager import Project
from app.gui.project_item_widget import ProjectItemWidget


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
        
        for path in paths:
            self.project_manager.add_file_to_project(active.id, path)
        
        updated_project = self.project_manager.get_project(active.id)
        if not updated_project:
            return
        
        idx = len(updated_project.files) - 1
        self.project_manager.set_active_file_in_project(active.id, idx)
        
        if active.id in self._widgets_map:
            item, widget = self._widgets_map[active.id]
            widget.set_expanded(True)
            self._update_item_size(item, widget)
        
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
        
        item.setSizeHint(widget.sizeHint())
        
        self.projects_list.addItem(item)
        self.projects_list.setItemWidget(item, widget)
        
        self._widgets_map[pid] = (item, widget)
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
        QTimer.singleShot(10, lambda: self._do_update_size(item, widget))
    
    def _do_update_size(self, item: QListWidgetItem, widget: ProjectItemWidget):
        """Фактическое обновление размера"""
        widget.adjustSize()
        new_size = widget.sizeHint()
        item.setSizeHint(new_size)
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
