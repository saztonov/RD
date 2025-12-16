"""
Диалог настройки папок для заданий OCR
"""

import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QLineEdit, QFileDialog,
                               QGroupBox, QDialogButtonBox)
from PySide6.QtCore import QSettings


def get_folder_settings():
    """Получить настройки папок"""
    settings = QSettings("RDApp", "FolderSettings")
    return {
        "new_jobs_dir": settings.value("new_jobs_dir", ""),
        "download_jobs_dir": settings.value("download_jobs_dir", "")
    }


def get_new_jobs_dir() -> str:
    """Получить папку для новых заданий"""
    return get_folder_settings()["new_jobs_dir"]


def get_download_jobs_dir() -> str:
    """Получить папку для скачивания заданий"""
    return get_folder_settings()["download_jobs_dir"]


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
        
        # Папка для новых заданий
        new_jobs_group = QGroupBox("Папка для новых заданий")
        new_jobs_layout = QVBoxLayout(new_jobs_group)
        
        new_jobs_layout.addWidget(QLabel("Сюда сохраняются результаты OCR задач:"))
        
        new_jobs_path_layout = QHBoxLayout()
        self.new_jobs_edit = QLineEdit()
        self.new_jobs_edit.setPlaceholderText("Выберите папку...")
        new_jobs_path_layout.addWidget(self.new_jobs_edit)
        
        new_jobs_browse_btn = QPushButton("Обзор...")
        new_jobs_browse_btn.clicked.connect(self._select_new_jobs_dir)
        new_jobs_path_layout.addWidget(new_jobs_browse_btn)
        
        new_jobs_layout.addLayout(new_jobs_path_layout)
        layout.addWidget(new_jobs_group)
        
        # Папка для скачивания заданий
        download_group = QGroupBox("Папка для скачивания заданий")
        download_layout = QVBoxLayout(download_group)
        
        download_layout.addWidget(QLabel("Сюда скачиваются задания при открытии в редакторе:"))
        
        download_path_layout = QHBoxLayout()
        self.download_edit = QLineEdit()
        self.download_edit.setPlaceholderText("Выберите папку...")
        download_path_layout.addWidget(self.download_edit)
        
        download_browse_btn = QPushButton("Обзор...")
        download_browse_btn.clicked.connect(self._select_download_dir)
        download_path_layout.addWidget(download_browse_btn)
        
        download_layout.addLayout(download_path_layout)
        layout.addWidget(download_group)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _load_settings(self):
        settings = get_folder_settings()
        self.new_jobs_edit.setText(settings["new_jobs_dir"])
        self.download_edit.setText(settings["download_jobs_dir"])
    
    def _select_new_jobs_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Папка для новых заданий")
        if dir_path:
            self.new_jobs_edit.setText(dir_path)
    
    def _select_download_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Папка для скачивания")
        if dir_path:
            self.download_edit.setText(dir_path)
    
    def _accept(self):
        from PySide6.QtWidgets import QMessageBox
        
        new_jobs_dir = self.new_jobs_edit.text().strip()
        download_dir = self.download_edit.text().strip()
        
        if not new_jobs_dir or not download_dir:
            QMessageBox.warning(self, "Ошибка", "Укажите обе папки")
            return
        
        if not os.path.exists(new_jobs_dir):
            os.makedirs(new_jobs_dir, exist_ok=True)
        
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)
        
        # Сохраняем
        settings = QSettings("RDApp", "FolderSettings")
        settings.setValue("new_jobs_dir", new_jobs_dir)
        settings.setValue("download_jobs_dir", download_dir)
        
        self.accept()

