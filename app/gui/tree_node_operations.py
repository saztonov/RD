"""Mixin для операций с узлами дерева проектов"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox, QFileDialog, QDialog, QTreeWidgetItem
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt

from app.tree_client import TreeNode, NodeType, NodeStatus
from app.gui.file_transfer_worker import FileTransferWorker, TransferTask, TransferType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


NODE_ICONS = {
    NodeType.PROJECT: "📁",
    NodeType.STAGE: "🏗",
    NodeType.SECTION: "📚",
    NodeType.TASK_FOLDER: "📂",
    NodeType.DOCUMENT: "📄",
}

STATUS_COLORS = {
    NodeStatus.ACTIVE: "#e0e0e0",
    NodeStatus.COMPLETED: "#4caf50",
    NodeStatus.ARCHIVED: "#9e9e9e",
}


class TreeNodeOperationsMixin:
    """Миксин для CRUD операций с узлами дерева"""
    
    def _create_project(self):
        """Создать новый проект"""
        name, ok = QInputDialog.getText(self, "Новый проект", "Название проекта:")
        if ok and name.strip():
            try:
                node = self.client.create_node(NodeType.PROJECT, name.strip())
                item = self._create_tree_item(node)
                self.tree.addTopLevelItem(item)
                self._add_placeholder(item, node)
                self.tree.setCurrentItem(item)
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def _create_child_node(self, parent_node: TreeNode, child_type):
        """Создать дочерний узел"""
        if isinstance(child_type, str):
            logger.debug(f"child_type is str: {child_type}, converting to NodeType")
            child_type = NodeType(child_type)
        
        logger.debug(f"_create_child_node: parent={parent_node.id}, child_type={child_type}")
        
        stage_types = self._stage_types if child_type == NodeType.STAGE else None
        section_types = self._section_types if child_type == NodeType.SECTION else None
        
        from app.gui.create_node_dialog import CreateNodeDialog
        dialog = CreateNodeDialog(self, child_type, stage_types, section_types)
        if dialog.exec_() == QDialog.Accepted:
            name, code = dialog.get_data()
            logger.debug(f"Dialog result: name={name}, code={code}")
            if name:
                try:
                    logger.debug(f"Creating node: type={child_type}, name={name}, parent={parent_node.id}, code={code}")
                    node = self.client.create_node(child_type, name, parent_node.id, code)
                    logger.debug(f"Node created: {node.id}")
                    parent_item = self._node_map.get(parent_node.id)
                    if parent_item:
                        if parent_item.childCount() == 1:
                            child = parent_item.child(0)
                            if child.data(0, self._get_user_role()) == "placeholder":
                                parent_item.removeChild(child)
                        
                        child_item = self._create_tree_item(node)
                        parent_item.addChild(child_item)
                        self._add_placeholder(child_item, node)
                        parent_item.setExpanded(True)
                        self.tree.setCurrentItem(child_item)
                except Exception as e:
                    logger.exception(f"Error creating child node: {e}")
                    QMessageBox.critical(self, "Ошибка", str(e))
    
    def _get_user_role(self):
        """Получить Qt.UserRole"""
        from PySide6.QtCore import Qt
        return Qt.UserRole
    
    def _close_if_open(self, r2_key: str):
        """Закрыть файл в редакторе если он открыт (по r2_key)"""
        if not r2_key:
            return
        
        from app.gui.folder_settings_dialog import get_projects_dir
        
        projects_dir = get_projects_dir()
        if not projects_dir:
            return
        
        # Формируем локальный путь из r2_key
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/"):]
        else:
            rel_path = r2_key
        
        cache_path = Path(projects_dir) / "cache" / rel_path
        
        # Получаем главное окно
        main_window = self.window()
        if not hasattr(main_window, '_current_pdf_path') or not main_window._current_pdf_path:
            return
        
        # Сравниваем пути
        try:
            current_path = Path(main_window._current_pdf_path).resolve()
            target_path = cache_path.resolve()
            
            if current_path == target_path:
                # Закрываем файл
                if hasattr(main_window, '_clear_interface'):
                    main_window._clear_interface()
                    logger.info(f"Closed file in editor: {cache_path}")
        except Exception as e:
            logger.error(f"Error checking open file: {e}")
    
    def _upload_file(self, node: TreeNode):
        """Добавить файл в папку заданий (асинхронная загрузка в R2)"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if not paths:
            return
        
        # Создаём worker для асинхронной загрузки
        self._upload_worker = FileTransferWorker(self)
        self._upload_target_node = node
        
        for path in paths:
            file_path = Path(path)
            filename = file_path.name
            file_size = file_path.stat().st_size
            r2_key = f"tree_docs/{node.id}/{filename}"
            
            task = TransferTask(
                transfer_type=TransferType.UPLOAD,
                local_path=str(file_path),
                r2_key=r2_key,
                node_id="",  # Будет заполнен после создания узла
                file_size=file_size,
                filename=filename,
                parent_node_id=node.id,
            )
            self._upload_worker.add_task(task)
        
        # Подключаем сигналы
        main_window = self.window()
        self._upload_worker.progress.connect(
            lambda msg, cur, tot: main_window.show_transfer_progress(msg, cur, tot)
        )
        self._upload_worker.finished_task.connect(self._on_upload_task_finished)
        self._upload_worker.all_finished.connect(self._on_all_uploads_finished)
        
        # Запускаем
        self._upload_worker.start()
    
    def _on_upload_task_finished(self, task: TransferTask, success: bool, error: str):
        """Обработка завершения загрузки одного файла"""
        if not success:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файл в R2:\n{task.filename}\n{error}")
            return
        
        logger.info(f"File uploaded to R2: {task.r2_key}")
        
        # Копируем файл в локальный кэш ДО создания узла (чтобы открытие было мгновенным)
        self._copy_to_cache(task.local_path, task.r2_key)
        
        parent_item = self._node_map.get(task.parent_node_id)
        
        try:
            doc_node = self.client.add_document(
                parent_id=task.parent_node_id,
                name=task.filename,
                r2_key=task.r2_key,
                file_size=task.file_size,
            )
            
            if parent_item:
                if parent_item.childCount() == 1:
                    child = parent_item.child(0)
                    if child.data(0, self._get_user_role()) == "placeholder":
                        parent_item.removeChild(child)
                
                child_item = self._create_tree_item(doc_node)
                parent_item.addChild(child_item)
                parent_item.setExpanded(True)
                self.tree.setCurrentItem(child_item)
                self.highlight_document(doc_node.id)
            
            logger.info(f"Document added: {doc_node.id} with r2_key={task.r2_key}")
            # Сигнал с node_id и r2_key для открытия
            self.file_uploaded_r2.emit(doc_node.id, task.r2_key)
            
        except Exception as e:
            logger.exception(f"Failed to add document: {e}")
            QMessageBox.critical(self, "Ошибка", f"Файл загружен в R2, но не добавлен в дерево:\n{e}")
    
    def _on_all_uploads_finished(self):
        """Все загрузки завершены"""
        main_window = self.window()
        main_window.hide_transfer_progress()
        self._upload_worker = None
    
    def _rename_node(self, node: TreeNode):
        """Переименовать узел (для документов также переименовывает в R2)"""
        new_name, ok = QInputDialog.getText(
            self, "Переименовать", "Новое название:", text=node.name
        )
        if ok and new_name.strip() and new_name.strip() != node.name:
            try:
                new_name_clean = new_name.strip()
                
                # Для документов переименовываем файл в R2
                if node.node_type == NodeType.DOCUMENT:
                    old_r2_key = node.attributes.get("r2_key", "")
                    
                    # Закрываем файл если он открыт в редакторе
                    self._close_if_open(old_r2_key)
                    
                    if old_r2_key:
                        from rd_core.r2_storage import R2Storage
                        from pathlib import PurePosixPath
                        
                        # Формируем новый ключ (меняем только имя файла)
                        # Используем PurePosixPath чтобы сохранить / в путях R2
                        old_path = PurePosixPath(old_r2_key)
                        new_r2_key = str(old_path.parent / new_name_clean)
                        
                        try:
                            r2 = R2Storage()
                            if r2.rename_object(old_r2_key, new_r2_key):
                                # Обновляем r2_key в attributes
                                node.attributes["r2_key"] = new_r2_key
                                node.attributes["original_name"] = new_name_clean
                                self.client.update_node(node.id, name=new_name_clean, attributes=node.attributes)
                                
                                # Переименовываем в локальном кэше
                                self._rename_cache_file(old_r2_key, new_r2_key)
                            else:
                                QMessageBox.warning(self, "Внимание", "Не удалось переименовать файл в R2")
                                return
                        except Exception as e:
                            logger.error(f"R2 rename error: {e}")
                            QMessageBox.warning(self, "Ошибка R2", f"Ошибка R2: {e}")
                            return
                    else:
                        self.client.update_node(node.id, name=new_name_clean)
                else:
                    self.client.update_node(node.id, name=new_name_clean)
                
                # Обновляем UI
                item = self._node_map.get(node.id)
                if item:
                    icon = NODE_ICONS.get(node.node_type, "📄")
                    if node.node_type == NodeType.DOCUMENT:
                        version_tag = f"[v{node.version}]" if node.version else "[v1]"
                        has_annotation = node.attributes.get("has_annotation", False)
                        ann_icon = " 📋" if has_annotation else ""
                        display_name = f"{icon} {version_tag} {new_name_clean}{ann_icon}"
                    elif node.code:
                        display_name = f"{icon} [{node.code}] {new_name_clean}"
                    else:
                        display_name = f"{icon} {new_name_clean}"
                    item.setText(0, display_name)
                    node.name = new_name_clean
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def _set_status(self, node: TreeNode, status: NodeStatus):
        """Установить статус узла"""
        try:
            self.client.update_node(node.id, status=status)
            item = self._node_map.get(node.id)
            if item:
                item.setForeground(0, QColor(STATUS_COLORS.get(status, "#e0e0e0")))
                node.status = status
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
    
    def _set_document_version(self, node: TreeNode, version: int):
        """Установить версию документа"""
        from PySide6.QtCore import Qt
        try:
            self.client.update_node(node.id, version=version)
            node.version = version
            
            # Обновляем отображение в дереве
            item = self._node_map.get(node.id)
            if item:
                icon = NODE_ICONS.get(node.node_type, "📄")
                has_annotation = node.attributes.get("has_annotation", False)
                ann_icon = " 📋" if has_annotation else ""
                display_name = f"{icon} {node.name}{ann_icon}"
                item.setText(0, display_name)
                item.setData(0, Qt.UserRole + 1, f"[v{version}]")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
    
    def _delete_node(self, node: TreeNode):
        """Удалить узел и все вложенные (из R2, кэша и Supabase)"""
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить '{node.name}' и все вложенные элементы?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                # Рекурсивно удаляем все документы в ветке из R2 и кэша
                self._delete_branch_files(node)
                
                if self.client.delete_node(node.id):
                    item = self._node_map.get(node.id)
                    if item:
                        parent = item.parent()
                        if parent:
                            parent.removeChild(item)
                        else:
                            idx = self.tree.indexOfTopLevelItem(item)
                            self.tree.takeTopLevelItem(idx)
                        del self._node_map[node.id]
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def _delete_branch_files(self, node: TreeNode):
        """Рекурсивно удалить все файлы документов в ветке из R2 и кэша"""
        from app.gui.folder_settings_dialog import get_projects_dir
        import shutil
        
        # Сначала рекурсивно обрабатываем дочерние узлы (чтобы закрыть файлы)
        try:
            children = self.client.get_children(node.id)
            for child in children:
                self._delete_branch_files(child)
        except Exception as e:
            logger.error(f"Failed to get children for deletion: {e}")
        
        # Если это документ - удаляем его файлы
        if node.node_type == NodeType.DOCUMENT:
            self._delete_document_files(node)
        
        # Если это task_folder - удаляем всю папку из кэша (после закрытия файлов)
        if node.node_type == NodeType.TASK_FOLDER:
            projects_dir = get_projects_dir()
            if projects_dir:
                cache_folder = Path(projects_dir) / "cache" / node.id
                if cache_folder.exists():
                    try:
                        shutil.rmtree(cache_folder)
                        logger.info(f"Deleted cache folder: {cache_folder}")
                    except Exception as e:
                        logger.error(f"Failed to delete cache folder: {e}")
    
    def _delete_document_files(self, node: TreeNode):
        """Удалить файлы документа из R2, локального кэша и БД"""
        from rd_core.r2_storage import R2Storage
        from app.gui.folder_settings_dialog import get_projects_dir
        from app.gui.file_operations import get_annotation_r2_key
        
        r2_key = node.attributes.get("r2_key", "")
        
        # Закрываем файл если он открыт в редакторе
        self._close_if_open(r2_key)
        
        # Удаляем из R2 (PDF и аннотацию)
        if r2_key:
            try:
                r2 = R2Storage()
                # Удаляем PDF
                r2.delete_object(r2_key)
                logger.info(f"Deleted from R2: {r2_key}")
                # Удаляем аннотацию
                ann_r2_key = get_annotation_r2_key(r2_key)
                r2.delete_object(ann_r2_key)
                logger.info(f"Deleted annotation from R2: {ann_r2_key}")
            except Exception as e:
                logger.error(f"Failed to delete from R2: {e}")
        
        # Удаляем из локального кэша (PDF и аннотацию)
        projects_dir = get_projects_dir()
        if projects_dir and r2_key:
            # Сохраняем структуру папок из R2
            if r2_key.startswith("tree_docs/"):
                rel_path = r2_key[len("tree_docs/"):]
            else:
                rel_path = r2_key
            
            cache_file = Path(projects_dir) / "cache" / rel_path
            if cache_file.exists():
                try:
                    cache_file.unlink()
                    logger.info(f"Deleted from cache: {cache_file}")
                except Exception as e:
                    logger.error(f"Failed to delete from cache: {e}")
            
            # Удаляем аннотацию из кэша
            ann_cache_file = cache_file.parent / f"{cache_file.stem}_annotation.json"
            if ann_cache_file.exists():
                try:
                    ann_cache_file.unlink()
                    logger.info(f"Deleted annotation from cache: {ann_cache_file}")
                except Exception as e:
                    logger.error(f"Failed to delete annotation from cache: {e}")
            
            # Удаляем пустую родительскую папку
            if cache_file.parent.exists() and not any(cache_file.parent.iterdir()):
                try:
                    cache_file.parent.rmdir()
                except Exception as e:
                    logger.error(f"Failed to delete empty cache folder: {e}")
        
        # Удаляем записи из БД (node_files)
        if node.id:
            try:
                node_files = self.client.get_node_files(node.id)
                for nf in node_files:
                    self.client.delete_node_file(nf.id)
                    logger.info(f"Deleted node_file from DB: {nf.id}")
            except Exception as e:
                logger.error(f"Failed to delete node_files from DB: {e}")
    
    def _copy_to_cache(self, src_path: str, r2_key: str):
        """Скопировать загружаемый файл в локальный кэш"""
        from app.gui.folder_settings_dialog import get_projects_dir
        import shutil
        
        projects_dir = get_projects_dir()
        if not projects_dir:
            return
        
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/"):]
        else:
            rel_path = r2_key
        
        cache_path = Path(projects_dir) / "cache" / rel_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            shutil.copy2(src_path, cache_path)
            logger.debug(f"Copied to cache: {cache_path}")
        except Exception as e:
            logger.error(f"Failed to copy to cache: {e}")
    
    def _rename_cache_file(self, old_r2_key: str, new_r2_key: str):
        """Переименовать файл в локальном кэше"""
        from app.gui.folder_settings_dialog import get_projects_dir
        
        projects_dir = get_projects_dir()
        if not projects_dir:
            return
        
        # Формируем пути
        def get_cache_path(r2_key: str) -> Path:
            if r2_key.startswith("tree_docs/"):
                rel_path = r2_key[len("tree_docs/"):]
            else:
                rel_path = r2_key
            return Path(projects_dir) / "cache" / rel_path
        
        old_cache = get_cache_path(old_r2_key)
        new_cache = get_cache_path(new_r2_key)
        
        if old_cache.exists():
            try:
                new_cache.parent.mkdir(parents=True, exist_ok=True)
                old_cache.rename(new_cache)
                logger.info(f"Renamed in cache: {old_cache} -> {new_cache}")
            except Exception as e:
                logger.error(f"Failed to rename in cache: {e}")
    
    def _remove_stamps_from_document(self, node: TreeNode):
        """Удалить рамки и QR-коды из PDF документа (скачать из R2, обработать, загрузить обратно)"""
        from rd_core.r2_storage import R2Storage
        from rd_core.pdf_stamp_remover import remove_stamps_from_pdf
        from app.gui.folder_settings_dialog import get_projects_dir
        
        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            QMessageBox.warning(self, "Ошибка", "R2 ключ файла не найден")
            return
        
        try:
            r2 = R2Storage()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка R2", f"Не удалось подключиться к R2:\n{e}")
            return
        
        # Скачиваем в папку проектов (с учётом структуры папок)
        projects_dir = get_projects_dir()
        if not projects_dir:
            QMessageBox.warning(self, "Ошибка", "Папка проектов не задана в настройках")
            return
        
        # Сохраняем структуру папок из R2
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/"):]
        else:
            rel_path = r2_key
        
        local_path = Path(projects_dir) / "cache" / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Закрываем файл если открыт в редакторе
        self._close_if_open(r2_key)
        
        # Если файл уже есть локально - используем его, иначе скачиваем
        if not local_path.exists():
            if not r2.download_file(r2_key, str(local_path)):
                QMessageBox.critical(self, "Ошибка", f"Не удалось скачать файл из R2:\n{r2_key}")
                return
        
        output_path = local_path.parent / f"{local_path.stem}_clean{local_path.suffix}"
        success, result = remove_stamps_from_pdf(str(local_path), str(output_path))
        
        if not success:
            QMessageBox.critical(self, "Ошибка", f"Не удалось обработать файл:\n{result}")
            return
        
        # Загружаем обработанный файл в R2
        parent_item = self._node_map.get(node.id)
        parent = parent_item.parent() if parent_item else None
        parent_node = parent.data(0, self._get_user_role()) if parent else None
        
        if not isinstance(parent_node, TreeNode):
            QMessageBox.warning(self, "Ошибка", "Не найден родительский узел")
            return
        
        new_r2_key = f"tree_docs/{parent_node.id}/{output_path.name}"
        
        if not r2.upload_file(str(output_path), new_r2_key):
            QMessageBox.critical(self, "Ошибка", "Не удалось загрузить обработанный файл в R2")
            return
        
        try:
            doc_node = self.client.add_document(
                parent_id=parent_node.id,
                name=output_path.name,
                r2_key=new_r2_key,
                file_size=output_path.stat().st_size,
            )
            child_item = self._create_tree_item(doc_node)
            parent.addChild(child_item)
            logger.info(f"Clean document added: {doc_node.id} with r2_key={new_r2_key}")
            
            QMessageBox.information(self, "Готово", f"Рамки удалены.\nФайл: {output_path.name}")
        except Exception as e:
            logger.exception(f"Error adding clean document: {e}")
            QMessageBox.warning(self, "Внимание", f"Файл загружен в R2, но не добавлен в дерево:\n{e}")

