"""Mixin для операций с узлами дерева проектов"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QInputDialog, QMessageBox, QFileDialog, QDialog, QTreeWidgetItem
from PySide6.QtGui import QColor

from app.tree_client import TreeNode, NodeType, NodeStatus

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
    
    def _upload_file(self, node: TreeNode):
        """Добавить файл в папку заданий (загрузка в R2)"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if not paths:
            return
        
        from rd_core.r2_storage import R2Storage
        
        try:
            r2 = R2Storage()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка R2", f"Не удалось подключиться к R2:\n{e}")
            return
        
        parent_item = self._node_map.get(node.id)
        
        for path in paths:
            file_path = Path(path)
            filename = file_path.name
            file_size = file_path.stat().st_size
            
            # Формируем r2_key: tree_docs/{task_folder_id}/{filename}
            r2_key = f"tree_docs/{node.id}/{filename}"
            
            # Загружаем в R2
            if not r2.upload_file(str(file_path), r2_key):
                QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файл в R2:\n{filename}")
                continue
            
            logger.info(f"File uploaded to R2: {r2_key}")
            
            try:
                doc_node = self.client.add_document(
                    parent_id=node.id,
                    name=filename,
                    r2_key=r2_key,
                    file_size=file_size,
                )
                
                if parent_item:
                    if parent_item.childCount() == 1:
                        child = parent_item.child(0)
                        if child.data(0, self._get_user_role()) == "placeholder":
                            parent_item.removeChild(child)
                    
                    child_item = self._create_tree_item(doc_node)
                    parent_item.addChild(child_item)
                    parent_item.setExpanded(True)
                
                logger.info(f"Document added: {doc_node.id} with r2_key={r2_key}")
                # Сигнал с r2_key для открытия
                self.file_uploaded_r2.emit(r2_key)
                
            except Exception as e:
                logger.exception(f"Failed to add document: {e}")
                QMessageBox.critical(self, "Ошибка", f"Файл загружен в R2, но не добавлен в дерево:\n{e}")
    
    def _rename_node(self, node: TreeNode):
        """Переименовать узел (только метаданные, R2 ключ не меняется)"""
        new_name, ok = QInputDialog.getText(
            self, "Переименовать", "Новое название:", text=node.name
        )
        if ok and new_name.strip() and new_name.strip() != node.name:
            try:
                self.client.update_node(node.id, name=new_name.strip())
                
                item = self._node_map.get(node.id)
                if item:
                    icon = NODE_ICONS.get(node.node_type, "📄")
                    code_part = f"[{node.code}] " if node.code else ""
                    item.setText(0, f"{icon} {code_part}{new_name.strip()}")
                    node.name = new_name.strip()
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
        try:
            self.client.update_node(node.id, version=version)
            node.version = version
            
            # Обновляем отображение в дереве
            item = self._node_map.get(node.id)
            if item:
                icon = NODE_ICONS.get(node.node_type, "📄")
                display_name = f"{icon} [v{version}] {node.name}"
                item.setText(0, display_name)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
    
    def _delete_node(self, node: TreeNode):
        """Удалить узел"""
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить '{node.name}' и все вложенные элементы?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
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
        
        # Скачиваем в папку проектов
        projects_dir = get_projects_dir()
        if not projects_dir:
            QMessageBox.warning(self, "Ошибка", "Папка проектов не задана в настройках")
            return
        
        download_dir = Path(projects_dir) / "cache"
        download_dir.mkdir(parents=True, exist_ok=True)
        
        filename = Path(r2_key).name
        local_path = download_dir / filename
        
        if not r2.download_file(r2_key, str(local_path)):
            QMessageBox.critical(self, "Ошибка", f"Не удалось скачать файл из R2:\n{r2_key}")
            return
        
        output_path = download_dir / f"{local_path.stem}_clean{local_path.suffix}"
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

