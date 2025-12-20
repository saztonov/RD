"""
Диалог настройки папок для проектов
"""

import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QLineEdit, QFileDialog,
                               QGroupBox, QDialogButtonBox)
from PySide6.QtCore import QSettings


def get_projects_dir() -> str:
    """Получить папку для проектов"""
    settings = QSettings("RDApp", "FolderSettings")
    return settings.value("projects_dir", "")


# Для обратной совместимости
def get_new_jobs_dir() -> str:
    return get_projects_dir()


def get_download_jobs_dir() -> str:
    return get_projects_dir()


class FolderSettingsDialog(QDialog):
    """Диалог настройки папок"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки папок")
        self.setMinimumWidth(500)
        self._setup_ui()
        self._load_settings()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Папка для проектов
        projects_group = QGroupBox("Папка для проектов")
        projects_layout = QVBoxLayout(projects_group)
        
        projects_layout.addWidget(QLabel("Сюда сохраняются и скачиваются файлы из дерева проектов:"))
        
        path_layout = QHBoxLayout()
        self.projects_edit = QLineEdit()
        self.projects_edit.setPlaceholderText("Выберите папку...")
        path_layout.addWidget(self.projects_edit)
        
        browse_btn = QPushButton("Обзор...")
        browse_btn.clicked.connect(self._select_dir)
        path_layout.addWidget(browse_btn)
        
        projects_layout.addLayout(path_layout)
        layout.addWidget(projects_group)
        
        layout.addStretch()
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _load_settings(self):
        self.projects_edit.setText(get_projects_dir())
    
    def _select_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Папка для проектов")
        if dir_path:
            self.projects_edit.setText(dir_path)
    
    def _accept(self):
        from PySide6.QtWidgets import QMessageBox
        
        projects_dir = self.projects_edit.text().strip()
        
        if not projects_dir:
            QMessageBox.warning(self, "Ошибка", "Укажите папку для проектов")
            return
        
        if not os.path.exists(projects_dir):
            os.makedirs(projects_dir, exist_ok=True)
        
        # Сохраняем
        settings = QSettings("RDApp", "FolderSettings")
        settings.setValue("projects_dir", projects_dir)
        
        self.accept()
