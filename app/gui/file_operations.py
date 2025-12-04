"""
Миксин для работы с файлами (открытие, сохранение, загрузка)
"""

import logging
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QDialog
from app.models import Document, Page
from app.pdf_utils import PDFDocument
from app.annotation_io import AnnotationIO

logger = logging.getLogger(__name__)


class FileOperationsMixin:
    """Миксин для операций с файлами"""
    
    def _create_empty_annotation(self, pdf_path: str) -> Document:
        """Создать пустой документ аннотации со страницами"""
        doc = Document(pdf_path=pdf_path)
        for page_num in range(self.pdf_document.page_count):
            dims = self.pdf_document.get_page_dimensions(page_num)
            if dims:
                page = Page(page_number=page_num, width=dims[0], height=dims[1])
                doc.pages.append(page)
        return doc
    
    def _open_pdf(self):
        """Открыть PDF файл"""
        active_project = self.project_manager.get_active_project()
        if not active_project:
            reply = QMessageBox.question(
                self, "Создать задание?",
                "Нет активного задания. Создать новое?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                name, ok = QInputDialog.getText(self, "Новое задание", "Название:")
                if ok and name.strip():
                    project_id = self.project_manager.create_project(name.strip())
                    active_project = self.project_manager.get_project(project_id)
                else:
                    return
            else:
                return
        
        file_path, _ = QFileDialog.getOpenFileName(self, "Открыть PDF", "", "PDF Files (*.pdf)")
        if not file_path:
            return
        
        self.project_manager.add_file_to_project(active_project.id, file_path)
        file_index = len(active_project.files) - 1
        self.project_manager.set_active_file_in_project(active_project.id, file_index)
        self._load_pdf_from_project(active_project.id, file_index)
    
    def _load_pdf_from_project(self, project_id: str, file_index: int):
        """Загрузить PDF из проекта"""
        project = self.project_manager.get_project(project_id)
        if not project or file_index < 0 or file_index >= len(project.files):
            return
        
        project_file = project.files[file_index]
        
        if self.pdf_document:
            self.pdf_document.close()
        
        self.page_images.clear()
        self.page_zoom_states.clear()
        
        self.pdf_document = PDFDocument(project_file.pdf_path)
        if not self.pdf_document.open():
            QMessageBox.critical(self, "Ошибка", "Не удалось открыть PDF")
            return
        
        self._current_project_id = project_id
        self._current_file_index = file_index
        
        cache_key = (project_id, file_index)
        if cache_key in self.annotations_cache:
            self.annotation_document = self.annotations_cache[cache_key]
        elif project_file.annotation_path and Path(project_file.annotation_path).exists():
            self.annotation_document = AnnotationIO.load_annotation(project_file.annotation_path)
        else:
            self.annotation_document = self._create_empty_annotation(project_file.pdf_path)
        
        self.current_page = 0
        self._render_current_page()
        self._update_ui()
        self.category_manager.extract_categories_from_document()
    
    def _load_cleaned_pdf(self, file_path: str, keep_annotation: bool = False):
        """Загрузить PDF (исходный или очищенный)"""
        if self.pdf_document:
            self.pdf_document.close()
        
        self.page_images.clear()
        self.page_zoom_states.clear()
        
        self.pdf_document = PDFDocument(file_path)
        if not self.pdf_document.open():
            QMessageBox.critical(self, "Ошибка", "Не удалось открыть PDF")
            return
        
        if not keep_annotation:
            self.annotation_document = self._create_empty_annotation(file_path)
        
        self.current_page = 0
        self._render_current_page()
        self._update_ui()
        self.category_manager.extract_categories_from_document()
    
    def _save_annotation(self):
        """Сохранить разметку в JSON"""
        if not self.annotation_document:
            return
        
        active_project = self.project_manager.get_active_project()
        if active_project:
            active_file = active_project.get_active_file()
            if active_file:
                pdf_path = Path(active_file.pdf_path)
                annotation_path = pdf_path.parent / f"{pdf_path.stem}_annotation.json"
                AnnotationIO.save_annotation(self.annotation_document, str(annotation_path))
                active_file.annotation_path = str(annotation_path)
                QMessageBox.information(self, "Успех", f"Разметка сохранена:\n{annotation_path}")
                return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить разметку", "blocks.json", "JSON Files (*.json)")
        if file_path:
            AnnotationIO.save_annotation(self.annotation_document, file_path)
            QMessageBox.information(self, "Успех", "Разметка сохранена")
    
    def _load_annotation(self):
        """Загрузить разметку из JSON"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить разметку", "", "JSON Files (*.json)")
        if not file_path:
            return
        
        loaded_doc = AnnotationIO.load_annotation(file_path)
        if loaded_doc:
            self.annotation_document = loaded_doc
            pdf_path = loaded_doc.pdf_path
            if Path(pdf_path).exists():
                self._load_cleaned_pdf(pdf_path, keep_annotation=True)
            elif self.pdf_document:
                self.current_page = 0
                self._render_current_page()
                self._update_ui()
            
            self.blocks_tree_manager.update_blocks_tree()
            self.category_manager.extract_categories_from_document()
            QMessageBox.information(self, "Успех", "Разметка загружена")
    
    def _save_current_annotation_to_cache(self):
        """Сохранить текущую аннотацию в кеш"""
        if self._current_project_id and self._current_file_index >= 0 and self.annotation_document:
            key = (self._current_project_id, self._current_file_index)
            self.annotations_cache[key] = self.annotation_document
    
    def _remove_stamps(self):
        """Удаление электронных штампов из PDF"""
        logger.info("Запуск удаления штампов")
        
        if not self.pdf_document or not self.annotation_document:
            QMessageBox.warning(self, "Внимание", "Сначала откройте PDF")
            return
        
        try:
            from app.gui.stamp_remover_dialog import StampRemoverDialog
            
            current_pdf_path = self.annotation_document.pdf_path
            dialog = StampRemoverDialog(current_pdf_path, self)
            
            if dialog.exec() == QDialog.Accepted:
                if dialog.cleaned_pdf_path:
                    reply = QMessageBox.question(
                        self, "Перезагрузить PDF",
                        "Загрузить очищенный PDF?\n\nВсе несохраненные изменения будут потеряны.",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        self._load_cleaned_pdf(dialog.cleaned_pdf_path)
                else:
                    QMessageBox.information(self, "Информация", "Изменений не было")
        
        except Exception as e:
            logger.error(f"Ошибка удаления штампов: {e}", exc_info=True)
            QMessageBox.critical(self, "Ошибка", f"Ошибка удаления штампов:\n{e}")

