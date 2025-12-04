"""
Менеджер проектов (заданий)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from PySide6.QtCore import QObject, Signal
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ProjectFile:
    """Файл в проекте"""
    pdf_path: str
    annotation_path: Optional[str] = None
    added_at: datetime = None
    
    def __post_init__(self):
        if self.added_at is None:
            self.added_at = datetime.now()
    
    @property
    def pdf_name(self) -> str:
        return Path(self.pdf_path).name


@dataclass
class Project:
    """Проект (задание)"""
    id: str
    name: str
    created_at: datetime = None
    files: List[ProjectFile] = field(default_factory=list)
    active_file_index: int = 0
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    def add_file(self, pdf_path: str, annotation_path: Optional[str] = None):
        """Добавить файл в проект"""
        file = ProjectFile(pdf_path=pdf_path, annotation_path=annotation_path)
        self.files.append(file)
    
    def remove_file(self, index: int):
        """Удалить файл из проекта"""
        if 0 <= index < len(self.files):
            del self.files[index]
            if self.active_file_index >= len(self.files) and self.files:
                self.active_file_index = len(self.files) - 1
    
    def get_active_file(self) -> Optional[ProjectFile]:
        """Получить активный файл"""
        if 0 <= self.active_file_index < len(self.files):
            return self.files[self.active_file_index]
        return None
    
    def set_active_file(self, index: int):
        """Установить активный файл"""
        if 0 <= index < len(self.files):
            self.active_file_index = index


class ProjectManager(QObject):
    """Менеджер проектов"""
    
    project_added = Signal(str)  # project_id
    project_updated = Signal(str)  # project_id
    project_removed = Signal(str)  # project_id
    project_selected = Signal(str)  # project_id
    file_added = Signal(str, int)  # project_id, file_index
    file_removed = Signal(str, int)  # project_id, file_index
    
    def __init__(self):
        super().__init__()
        self.projects: Dict[str, Project] = {}
        self.active_project_id: Optional[str] = None
        self._project_counter = 0
    
    def create_project(self, name: str) -> str:
        """Создать новый проект"""
        self._project_counter += 1
        project_id = f"project_{self._project_counter}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        project = Project(id=project_id, name=name)
        self.projects[project_id] = project
        self.project_added.emit(project_id)
        
        # Автоматически активируем первый проект
        if not self.active_project_id:
            self.set_active_project(project_id)
        
        return project_id
    
    def remove_project(self, project_id: str):
        """Удалить проект"""
        if project_id in self.projects:
            del self.projects[project_id]
            self.project_removed.emit(project_id)
            
            # Если удалён активный проект, выбираем другой
            if self.active_project_id == project_id:
                if self.projects:
                    self.set_active_project(next(iter(self.projects.keys())))
                else:
                    self.active_project_id = None
    
    def get_project(self, project_id: str) -> Optional[Project]:
        """Получить проект по ID"""
        return self.projects.get(project_id)
    
    def get_active_project(self) -> Optional[Project]:
        """Получить активный проект"""
        if self.active_project_id:
            return self.projects.get(self.active_project_id)
        return None
    
    def set_active_project(self, project_id: str):
        """Установить активный проект"""
        if project_id in self.projects:
            self.active_project_id = project_id
            self.project_selected.emit(project_id)
    
    def add_file_to_project(self, project_id: str, pdf_path: str, annotation_path: Optional[str] = None):
        """Добавить файл в проект"""
        project = self.get_project(project_id)
        if project:
            project.add_file(pdf_path, annotation_path)
            file_index = len(project.files) - 1
            self.file_added.emit(project_id, file_index)
            self.project_updated.emit(project_id)
    
    def remove_file_from_project(self, project_id: str, file_index: int):
        """Удалить файл из проекта"""
        project = self.get_project(project_id)
        if project:
            project.remove_file(file_index)
            self.file_removed.emit(project_id, file_index)
            self.project_updated.emit(project_id)
    
    def set_active_file_in_project(self, project_id: str, file_index: int):
        """Установить активный файл в проекте"""
        project = self.get_project(project_id)
        if project:
            project.set_active_file(file_index)
            self.project_updated.emit(project_id)
    
    def get_all_projects(self) -> List[Project]:
        """Получить все проекты"""
        return list(self.projects.values())






