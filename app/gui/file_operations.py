"""
Миксин для работы с файлами (открытие, сохранение, загрузка)
"""

import logging
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from rd_core.models import Document, Page
from rd_core.pdf_utils import PDFDocument
from rd_core.annotation_io import AnnotationIO
from app.gui.file_auto_save import FileAutoSaveMixin, get_annotation_path, get_annotation_r2_key
from app.gui.file_download import FileDownloadMixin

logger = logging.getLogger(__name__)

# Re-export для обратной совместимости
__all__ = ['FileOperationsMixin', 'get_annotation_path', 'get_annotation_r2_key']


class FileOperationsMixin(FileAutoSaveMixin, FileDownloadMixin):
    """Миксин для операций с файлами"""
    
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
            from app.gui.tree_node_operations import NODE_ICONS
            from app.tree_client import NodeType
            from PySide6.QtCore import Qt
            
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
                        icon = NODE_ICONS.get(node.node_type, "📄")
                        version_tag = f"[v{node.version}]" if node.version else "[v1]"
                        ann_icon = "📋" if has_annotation else ""
                        display_name = f"{icon} {version_tag} {node.name} {ann_icon}".strip()
                        item.setText(0, display_name)
        except Exception as e:
            logger.debug(f"Update has_annotation failed: {e}")
    
    def _load_annotation_if_exists(self, pdf_path: str, r2_key: str = ""):
        """Загрузить annotation.json если существует (локально или в R2)"""
        from app.gui.toast import show_toast
        from rd_core.annotation_io import MigrationResult
        
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
        
        # Загрузить и мигрировать локальный файл
        if ann_path.exists():
            loaded, result = AnnotationIO.load_and_migrate(str(ann_path))
            
            # Ошибка загрузки - предлагаем создать заново
            if not result.success:
                error_msg = "; ".join(result.errors)
                logger.error(f"Annotation load failed: {error_msg}")
                
                from PySide6.QtWidgets import QMessageBox
                reply = QMessageBox.warning(
                    self,
                    "Ошибка аннотации",
                    f"Не удалось загрузить файл разметки:\n{error_msg}\n\n"
                    "Создать новый файл разметки?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes:
                    # Удаляем битый файл и создаём пустую аннотацию
                    try:
                        ann_path.unlink()
                    except Exception:
                        pass
                    show_toast(self, "Создана новая разметка", success=True)
                    return False  # Будет создана пустая аннотация
                else:
                    return False
            
            if loaded:
                self.annotation_document = loaded
                logger.info(f"Annotation loaded: {ann_path}")
                
                # Миграция формата выполнена - сохраняем и уведомляем
                if result.migrated:
                    logger.info(f"Annotation format migrated, saving")
                    AnnotationIO.save_annotation(loaded, str(ann_path))
                    # Синхронизируем с R2
                    self._sync_annotation_to_r2()
                    
                    # Уведомление пользователю
                    warn_count = len(result.warnings)
                    if warn_count > 0:
                        show_toast(
                            self, 
                            f"Разметка обновлена до актуального формата ({warn_count} изм.)",
                            duration=3000,
                            success=True
                        )
                    else:
                        show_toast(self, "Формат разметки обновлён", success=True)
                
                # Аннотация уже есть - значит синхронизирована
                self._annotation_synced = True
                # Обновляем флаг has_annotation в дереве
                self._update_has_annotation_flag(True)
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
        # Сохранить изменения предыдущего файла
        self._flush_pending_save()
        
        if self.pdf_document:
            self.pdf_document.close()
        
        self.page_images.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        
        # Сброс флага синхронизации для нового файла
        self._annotation_synced = False
        
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
        
        # Обновляем дерево групп
        if hasattr(self, '_update_groups_tree'):
            self._update_groups_tree()
        
        # Загружаем OCR result file для preview
        if hasattr(self, '_load_ocr_result_file'):
            self._load_ocr_result_file()
        
        # Обновляем заголовок
        self.setWindowTitle(f"PDF Annotation Tool - {Path(pdf_path).name}")
    
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
        from app.gui.toast import show_toast
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить разметку", "", "JSON Files (*.json)"
        )
        if not file_path:
            return
        
        loaded_doc, result = AnnotationIO.load_and_migrate(file_path)
        
        if not result.success:
            error_msg = "; ".join(result.errors)
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось загрузить разметку:\n{error_msg}"
            )
            return
        
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
            
            # Сохранить если была миграция
            if result.migrated:
                AnnotationIO.save_annotation(loaded_doc, file_path)
                show_toast(self, "Разметка загружена и обновлена", success=True)
            else:
                show_toast(self, "Разметка загружена", success=True)
            
            self.blocks_tree_manager.update_blocks_tree()
    
    def _on_annotation_replaced(self, r2_key: str):
        """Обработчик замены аннотации в дереве проектов"""
        from app.gui.toast import show_toast
        
        # Проверяем совпадает ли r2_key с текущим открытым документом
        if not hasattr(self, '_current_r2_key') or self._current_r2_key != r2_key:
            return
        
        if not self._current_pdf_path:
            return
        
        try:
            # Скачиваем обновлённую аннотацию из R2
            from rd_core.r2_storage import R2Storage
            ann_r2_key = get_annotation_r2_key(r2_key)
            ann_path = get_annotation_path(self._current_pdf_path)
            
            r2 = R2Storage()
            if not r2.download_file(ann_r2_key, str(ann_path)):
                logger.warning(f"Не удалось скачать аннотацию из R2: {ann_r2_key}")
                return
            
            # Загружаем с миграцией
            loaded_doc, result = AnnotationIO.load_and_migrate(str(ann_path))
            if not result.success or not loaded_doc:
                logger.warning(f"Не удалось загрузить аннотацию: {result.errors}")
                return
            
            # Заменяем текущую аннотацию
            self.annotation_document = loaded_doc
            self._annotation_synced = True
            
            # Если была миграция - сохраняем и синхронизируем
            if result.migrated:
                AnnotationIO.save_annotation(loaded_doc, str(ann_path))
                self._sync_annotation_to_r2()
            
            # Обновляем отображение
            self._render_current_page()
            if hasattr(self, 'blocks_tree_manager') and self.blocks_tree_manager:
                self.blocks_tree_manager.update_blocks_tree()
            if hasattr(self, '_update_groups_tree'):
                self._update_groups_tree()
            
            logger.info(f"Аннотация обновлена из R2: {ann_r2_key}")
            show_toast(self, "Аннотация обновлена", success=True)
            
        except Exception as e:
            logger.error(f"Ошибка обновления аннотации: {e}")
