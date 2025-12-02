"""
Боковая панель с заданиями
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, 
                               QListWidget, QListWidgetItem, QProgressBar, 
                               QHBoxLayout, QGroupBox, QMessageBox, QFrame)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from app.gui.task_manager import TaskStatus, TaskType


class TaskItemWidget(QWidget):
    """Виджет элемента задания в списке"""
    
    clicked = Signal(str)  # task_id
    cancel_clicked = Signal(str)  # task_id
    
    def __init__(self, task):
        super().__init__()
        self.task = task
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Заголовок
        header_layout = QHBoxLayout()
        
        # Иконка типа
        icon = "📝" if self.task.task_type == TaskType.OCR else "🔖"
        type_label = QLabel(icon)
        header_layout.addWidget(type_label)
        
        # Название
        self.name_label = QLabel(self.task.name)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("color: #e0e0e0;")
        header_layout.addWidget(self.name_label, stretch=1)
        
        layout.addLayout(header_layout)
        
        # Статус
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: #cccccc;")
        self._update_status_label()
        layout.addWidget(self.status_label)
        
        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                background-color: #2d2d30;
                text-align: center;
                color: #e0e0e0;
            }
            QProgressBar::chunk {
                background-color: #0e639c;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Кнопка отмены (только для запущенных)
        if self.task.status == TaskStatus.RUNNING:
            cancel_btn = QPushButton("❌ Отменить")
            cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #5e2d2d;
                    color: #e0e0e0;
                    border: none;
                    padding: 4px 8px;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #7e3d3d;
                }
            """)
            cancel_btn.clicked.connect(lambda: self.cancel_clicked.emit(self.task.id))
            layout.addWidget(cancel_btn)
        
        # Сообщение об ошибке
        if self.task.status == TaskStatus.ERROR and self.task.error_message:
            error_label = QLabel(f"Ошибка: {self.task.error_message[:50]}...")
            error_label.setStyleSheet("color: #ff6b6b; font-size: 10px;")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)
        
        self.setStyleSheet(self._get_style())
    
    def _update_status_label(self):
        status_text = {
            TaskStatus.PENDING: "⏳ Ожидание",
            TaskStatus.RUNNING: "⚙️ Выполняется",
            TaskStatus.SUCCESS: "✅ Завершено",
            TaskStatus.ERROR: "❌ Ошибка",
            TaskStatus.CANCELLED: "🚫 Отменено"
        }
        self.status_label.setText(status_text.get(self.task.status, ""))
    
    def _get_style(self):
        colors = {
            TaskStatus.PENDING: "#3e3e42",
            TaskStatus.RUNNING: "#2d4a5e",
            TaskStatus.SUCCESS: "#2d4a3e",
            TaskStatus.ERROR: "#5e2d2d",
            TaskStatus.CANCELLED: "#3e3e42"
        }
        bg_color = colors.get(self.task.status, "#2d2d30")
        return f"""
            TaskItemWidget {{
                background-color: {bg_color};
                border: 1px solid #555;
                border-radius: 4px;
            }}
        """
    
    def update_task(self, task):
        """Обновить данные задания"""
        self.task = task
        self._update_status_label()
        
        # Обновить прогресс
        if task.max_progress > 0:
            progress_percent = int((task.progress / task.max_progress) * 100)
            self.progress_bar.setValue(progress_percent)
        
        self.setStyleSheet(self._get_style())
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.task.id)
        super().mousePressEvent(event)


class TaskSidebar(QWidget):
    """Боковая панель со списком заданий"""
    
    task_selected = Signal(str)  # task_id
    
    def __init__(self, task_manager):
        super().__init__()
        self.task_manager = task_manager
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Группа заданий
        group = QGroupBox("Задания")
        group.setStyleSheet("""
            QGroupBox {
                color: #bbbbbb;
                font-weight: bold;
                border: 1px solid #3e3e42;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #252526;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        group_layout = QVBoxLayout(group)
        
        # Список заданий
        self.tasks_list = QListWidget()
        self.tasks_list.setSpacing(5)
        self.tasks_list.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: #1e1e1e;
            }
            QListWidget::item {
                border: none;
                padding: 0px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: transparent;
            }
        """)
        group_layout.addWidget(self.tasks_list)
        
        # Кнопка очистки завершенных
        clear_btn = QPushButton("🗑️ Очистить завершенные")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: #e0e0e0;
                border: none;
                padding: 6px 12px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4e4e52;
            }
        """)
        clear_btn.clicked.connect(self._clear_completed)
        group_layout.addWidget(clear_btn)
        
        layout.addWidget(group)
    
    def _connect_signals(self):
        """Подключить сигналы от TaskManager"""
        self.task_manager.task_added.connect(self._on_task_added)
        self.task_manager.task_updated.connect(self._on_task_updated)
    
    def _on_task_added(self, task_id: str):
        """Обработка добавления задания"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        
        # Создать виджет задания
        item = QListWidgetItem(self.tasks_list)
        widget = TaskItemWidget(task)
        widget.clicked.connect(self.task_selected.emit)
        widget.cancel_clicked.connect(self._on_cancel_task)
        
        item.setSizeHint(widget.sizeHint())
        self.tasks_list.addItem(item)
        self.tasks_list.setItemWidget(item, widget)
        
        # Прокрутить к новому заданию
        self.tasks_list.scrollToItem(item)
    
    def _on_task_updated(self, task_id: str):
        """Обработка обновления задания"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        
        # Найти и обновить виджет
        for i in range(self.tasks_list.count()):
            item = self.tasks_list.item(i)
            widget = self.tasks_list.itemWidget(item)
            if widget and widget.task.id == task_id:
                widget.update_task(task)
                item.setSizeHint(widget.sizeHint())
                break
    
    def _on_cancel_task(self, task_id: str):
        """Обработка отмены задания"""
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Отменить задание?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.task_manager.cancel_task(task_id)
    
    def _clear_completed(self):
        """Очистить завершенные задания из списка"""
        to_remove = []
        
        for i in range(self.tasks_list.count()):
            item = self.tasks_list.item(i)
            widget = self.tasks_list.itemWidget(item)
            if widget and widget.task.status in (TaskStatus.SUCCESS, TaskStatus.ERROR, TaskStatus.CANCELLED):
                to_remove.append(i)
        
        # Удалить с конца чтобы индексы не сбивались
        for i in reversed(to_remove):
            item = self.tasks_list.takeItem(i)
            widget = self.tasks_list.itemWidget(item)
            if widget:
                task_id = widget.task.id
                if task_id in self.task_manager.tasks:
                    del self.task_manager.tasks[task_id]

