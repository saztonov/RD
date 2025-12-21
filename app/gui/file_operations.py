"""
Миксин для работы с файлами (открытие, сохранение, загрузка)
"""

import logging
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox
from rd_core.models import Document, Page
from rd_core.pdf_utils import PDFDocument
from rd_core.annotation_io import AnnotationIO

logger = logging.getLogger(__name__)


def get_annotation_path(pdf_path: str) -> Path:
    """Путь к annotation.json для PDF файла"""
    p = Path(pdf_path)
    return p.parent / f"{p.stem}_annotation.json"


def get_annotation_r2_key(pdf_r2_key: str) -> str:
    """R2 ключ для annotation.json"""
    from pathlib import PurePosixPath
    p = PurePosixPath(pdf_r2_key)
    return str(p.parent / f"{p.stem}_annotation.json")


class FileOperationsMixin:
    """Миксин для операций с файлами"""
    
    _current_r2_key: str = ""  # R2 ключ текущего PDF
    _current_node_id: str = ""  # ID узла документа в дереве
    
    def _auto_save_annotation(self):
        """Авто-сохранение разметки при изменении блоков"""
        if not self.annotation_document or not self._current_pdf_path:
            return
        
        ann_path = get_annotation_path(self._current_pdf_path)
        try:
            AnnotationIO.save_annotation(self.annotation_document, str(ann_path))
            logger.debug(f"Annotation auto-saved: {ann_path}")
            
            # Синхронизация с R2 (в фоне)
            if hasattr(self, '_current_r2_key') and self._current_r2_key:
                self._sync_annotation_to_r2()
        except Exception as e:
            logger.error(f"Auto-save annotation failed: {e}")
    
    def _sync_annotation_to_r2(self):
        """Синхронизировать annotation.json с R2"""
        if not self._current_r2_key or not self._current_pdf_path:
            return
        
        ann_path = get_annotation_path(self._current_pdf_path)
        if not ann_path.exists():
            return
        
        try:
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(self._current_r2_key)
            r2.upload_file(str(ann_path), ann_r2_key)
            logger.debug(f"Annotation synced to R2: {ann_r2_key}")
            
            # Обновить атрибут has_annotation в дереве
            self._update_has_annotation_flag(True)
        except Exception as e:
            logger.error(f"Sync annotation to R2 failed: {e}")
    
    def _update_has_annotation_flag(self, has_annotation: bool):
        """Обновить флаг has_annotation в узле дерева"""
        if not hasattr(self, '_current_node_id') or not self._current_node_id:
            return
        
        try:
            from app.tree_client import TreeClient
            client = TreeClient()
            node = client.get_node(self._current_node_id)
            if node:
                attrs = node.attributes.copy()
                attrs["has_annotation"] = has_annotation
                client.update_node(self._current_node_id, attributes=attrs)
                
                # Обновить отображение в дереве
                if hasattr(self, 'project_tree') and self.project_tree:
                    item = self.project_tree._node_map.get(self._current_node_id)
                    if item:
                        node.attributes = attrs
                        from app.gui.tree_node_operations import NODE_ICONS
                        from app.tree_client import NodeType
                        icon = NODE_ICONS.get(node.node_type, "📄")
                        version_tag = f"[v{node.version}]" if node.version else "[v1]"
                        ann_icon = "📋" if has_annotation else ""
                        display_name = f"{icon} {version_tag} {node.name} {ann_icon}".strip()
                        item.setText(0, display_name)
        except Exception as e:
            logger.debug(f"Update has_annotation failed: {e}")
    
    def _load_annotation_if_exists(self, pdf_path: str, r2_key: str = ""):
        """Загрузить annotation.json если существует (локально или в R2)"""
        ann_path = get_annotation_path(pdf_path)
        
        # Попробовать скачать из R2 если нет локально
        if not ann_path.exists() and r2_key:
            try:
                from rd_core.r2_storage import R2Storage
                r2 = R2Storage()
                ann_r2_key = get_annotation_r2_key(r2_key)
                r2.download_file(ann_r2_key, str(ann_path))
            except Exception as e:
                logger.debug(f"No annotation in R2 or error: {e}")
        
        # Загрузить локальный файл
        if ann_path.exists():
            loaded = AnnotationIO.load_annotation(str(ann_path))
            if loaded:
                self.annotation_document = loaded
                logger.info(f"Annotation loaded: {ann_path}")
                return True
        return False
    
    def _create_empty_annotation(self, pdf_path: str) -> Document:
        """Создать пустой документ аннотации со страницами"""
        doc = Document(pdf_path=pdf_path)
        for page_num in range(self.pdf_document.page_count):
            if page_num in self.page_images:
                img = self.page_images[page_num]
                page = Page(page_number=page_num, width=img.width, height=img.height)
            else:
                dims = self.pdf_document.get_page_dimensions(page_num)
                if dims:
                    page = Page(page_number=page_num, width=dims[0], height=dims[1])
                else:
                    page = Page(page_number=page_num, width=595, height=842)
            doc.pages.append(page)
        return doc
    
    def _open_pdf(self):
        """Открыть PDF файл через диалог"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Открыть PDF", "", "PDF Files (*.pdf)"
        )
        if file_path:
            self._open_pdf_file(file_path)
    
    def _open_pdf_file(self, pdf_path: str, r2_key: str = ""):
        """Открыть PDF файл напрямую"""
        if self.pdf_document:
            self.pdf_document.close()
        
        self.page_images.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        
        self.pdf_document = PDFDocument(pdf_path)
        if not self.pdf_document.open() or self.pdf_document.page_count == 0:
            QMessageBox.warning(self, "Ошибка", "PDF файл пустой или повреждён")
            return
        
        self.current_page = 0
        self._current_pdf_path = pdf_path
        self._current_r2_key = r2_key
        
        # Пробуем загрузить существующую разметку
        if not self._load_annotation_if_exists(pdf_path, r2_key):
            # Создаём пустой документ аннотации
            self.annotation_document = self._create_empty_annotation(pdf_path)
        
        # Рендерим первую страницу
        self._render_current_page()
        self._update_ui()
        
        # Обновляем заголовок
        self.setWindowTitle(f"PDF Annotation Tool - {Path(pdf_path).name}")
    
    def _on_tree_file_uploaded_r2(self, r2_key: str):
        """Открыть загруженный файл из R2 в редакторе"""
        self._on_tree_document_selected("", r2_key)
    
    def _on_tree_document_selected(self, node_id: str, r2_key: str):
        """Открыть документ из дерева (скачать из R2 и открыть)"""
        from rd_core.r2_storage import R2Storage
        from app.gui.folder_settings_dialog import get_projects_dir
        
        if not r2_key:
            return
        
        projects_dir = get_projects_dir()
        if not projects_dir:
            QMessageBox.warning(self, "Ошибка", "Папка проектов не задана в настройках")
            return
        
        try:
            r2 = R2Storage()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка R2", f"Не удалось подключиться к R2:\n{e}")
            return
        
        # Сохраняем структуру папок из R2 (tree_docs/{folder_id}/{filename})
        from pathlib import PurePosixPath
        r2_path = PurePosixPath(r2_key)
        
        # Создаём локальный путь: cache/{r2_key без tree_docs/}
        # Например: cache/{folder_id}/{filename}
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/"):]
        else:
            rel_path = r2_key
        
        local_path = Path(projects_dir) / "cache" / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Пропускаем скачивание если файл уже есть
        if not local_path.exists():
            logger.info(f"Downloading from R2: {r2_key} -> {local_path}")
            if not r2.download_file(r2_key, str(local_path)):
                QMessageBox.critical(self, "Ошибка", f"Не удалось скачать файл из R2:\n{r2_key}")
                return
        
        self._current_r2_key = r2_key
        self._current_node_id = node_id
        self._open_pdf_file(str(local_path), r2_key=r2_key)
    
    def _save_annotation(self):
        """Сохранить разметку в JSON"""
        if not self.annotation_document:
            return
        
        # Определяем путь по умолчанию рядом с PDF
        default_path = ""
        if hasattr(self, '_current_pdf_path') and self._current_pdf_path:
            pdf_path = Path(self._current_pdf_path)
            default_path = str(pdf_path.parent / f"{pdf_path.stem}_annotation.json")
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить разметку", default_path, "JSON Files (*.json)"
        )
        if file_path:
            AnnotationIO.save_annotation(self.annotation_document, file_path)
            from app.gui.toast import show_toast
            show_toast(self, "Разметка сохранена")
    
    def _load_annotation(self):
        """Загрузить разметку из JSON"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить разметку", "", "JSON Files (*.json)"
        )
        if not file_path:
            return
        
        loaded_doc = AnnotationIO.load_annotation(file_path)
        if loaded_doc:
            # Поддержка относительного пути
            try:
                pdf_path_obj = Path(loaded_doc.pdf_path)
                if not pdf_path_obj.is_absolute():
                    resolved = (Path(file_path).parent / pdf_path_obj).resolve()
                    loaded_doc.pdf_path = str(resolved)
            except Exception:
                pass

            self.annotation_document = loaded_doc
            pdf_path = loaded_doc.pdf_path
            if Path(pdf_path).exists():
                self._open_pdf_file(pdf_path)
                # Восстанавливаем аннотацию после открытия
                self.annotation_document = loaded_doc
                self._render_current_page()
            
            self.blocks_tree_manager.update_blocks_tree()
            from app.gui.toast import show_toast
            show_toast(self, "Разметка загружена")
