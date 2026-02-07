"""Операции с аннотациями документов в дереве проектов"""
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.tree_client import FileType, NodeType, TreeNode

if TYPE_CHECKING:
    from app.gui.project_tree.widget import ProjectTreeWidget

logger = logging.getLogger(__name__)


class AnnotationOperations:
    """
    Операции с аннотациями документов.

    Отвечает за:
    - Копирование/вставка аннотаций
    - Загрузка аннотаций из файла
    - Определение и назначение штампов
    """

    def __init__(self, widget: "ProjectTreeWidget"):
        """
        Args:
            widget: Родительский виджет ProjectTreeWidget
        """
        self._widget = widget
        self._copied_annotation: Dict = {}  # {"json": str, "source_r2_key": str}

    @property
    def has_copied(self) -> bool:
        """Есть ли скопированная аннотация"""
        return bool(self._copied_annotation)

    def copy_annotation(self, node: TreeNode) -> None:
        """Скопировать аннотацию документа в буфер"""
        from app.gui.file_operations import get_annotation_r2_key
        from rd_core.r2_storage import R2Storage

        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            return

        try:
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)
            json_content = r2.download_text(ann_r2_key)

            if json_content:
                self._copied_annotation = {
                    "json": json_content,
                    "source_r2_key": r2_key,
                }
                self._widget.status_label.setText("📋 Аннотация скопирована")
                logger.info(f"Annotation copied from {ann_r2_key}")
            else:
                QMessageBox.warning(
                    self._widget, "Ошибка", "Не удалось загрузить аннотацию"
                )
        except Exception as e:
            logger.error(f"Copy annotation failed: {e}")
            QMessageBox.critical(self._widget, "Ошибка", f"Ошибка копирования: {e}")

    def paste_annotation(self, node: TreeNode) -> None:
        """Вставить аннотацию из буфера в документ"""
        if self._check_locked(node):
            return

        from app.gui.file_operations import get_annotation_r2_key
        from rd_core.r2_storage import R2Storage

        if not self._copied_annotation:
            return

        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            return

        try:
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)

            if r2.upload_text(self._copied_annotation["json"], ann_r2_key):
                # Обновляем флаг has_annotation
                attrs = node.attributes.copy()
                attrs["has_annotation"] = True
                self._widget.client.update_node(node.id, attributes=attrs)

                # Обновляем статус PDF
                self._update_pdf_status(node, r2_key, r2)

                self._widget.status_label.setText("📥 Аннотация вставлена")
                logger.info(f"Annotation pasted to {ann_r2_key}")

                # Сигнал для обновления открытого документа
                self._widget.annotation_replaced.emit(r2_key)
            else:
                QMessageBox.warning(
                    self._widget, "Ошибка", "Не удалось сохранить аннотацию"
                )
        except Exception as e:
            logger.error(f"Paste annotation failed: {e}")
            QMessageBox.critical(self._widget, "Ошибка", f"Ошибка вставки: {e}")

    def upload_from_file(self, node: TreeNode) -> None:
        """Диалог загрузки аннотации блоков из файла"""
        if self._check_locked(node):
            return

        from app.gui.file_operations import get_annotation_r2_key
        from rd_core.r2_storage import R2Storage

        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            QMessageBox.warning(
                self._widget, "Ошибка", "Документ не имеет привязки к R2"
            )
            return

        # Диалог выбора файла
        file_path, _ = QFileDialog.getOpenFileName(
            self._widget,
            "Выберите файл аннотации",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            # Читаем содержимое файла
            with open(file_path, "r", encoding="utf-8") as f:
                json_content = f.read()

            # Валидация JSON
            json.loads(json_content)

            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)

            # Загружаем в R2
            if not r2.upload_text(json_content, ann_r2_key):
                QMessageBox.critical(
                    self._widget, "Ошибка", "Не удалось загрузить аннотацию в R2"
                )
                return

            logger.info(f"Annotation uploaded to R2: {ann_r2_key}")

            # Обновляем флаг has_annotation
            attrs = node.attributes.copy()
            attrs["has_annotation"] = True
            self._widget.client.update_node(node.id, attributes=attrs)

            # Регистрируем файл в node_files
            file_size = Path(file_path).stat().st_size
            self._widget.client.upsert_node_file(
                node_id=node.id,
                file_type=FileType.ANNOTATION,
                r2_key=ann_r2_key,
                file_name=Path(ann_r2_key).name,
                file_size=file_size,
                mime_type="application/json",
            )

            logger.info(f"Annotation registered in Supabase: node_id={node.id}")

            # Обновляем статус PDF
            self._update_pdf_status(node, r2_key, r2)

            self._widget.status_label.setText("📤 Аннотация загружена")
            self._widget.annotation_replaced.emit(r2_key)

            QMessageBox.information(
                self._widget, "Успех", "Аннотация блоков успешно загружена"
            )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in annotation file: {e}")
            QMessageBox.critical(self._widget, "Ошибка", f"Неверный формат JSON:\n{e}")
        except Exception as e:
            logger.error(f"Upload annotation failed: {e}")
            QMessageBox.critical(
                self._widget, "Ошибка", f"Ошибка загрузки аннотации:\n{e}"
            )

    def detect_and_assign_stamps(self, node: TreeNode) -> None:
        """Определить и назначить штамп на всех страницах PDF"""
        if self._check_locked(node):
            return

        from app.gui.file_operations import get_annotation_r2_key
        from rd_core.models import BlockType, Document
        from rd_core.r2_storage import R2Storage

        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            QMessageBox.warning(
                self._widget, "Ошибка", "Документ не имеет привязки к R2"
            )
            return

        try:
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)

            # Загрузить аннотацию из R2
            json_content = r2.download_text(ann_r2_key)
            if not json_content:
                QMessageBox.warning(
                    self._widget, "Ошибка", "Аннотация документа не найдена"
                )
                return

            data = json.loads(json_content)
            doc, _ = Document.from_dict(data)

            # Получить категорию stamp из базы
            stamp_category = self._widget.client.get_image_category_by_code("stamp")
            stamp_category_id = stamp_category.get("id") if stamp_category else None

            modified_count = 0

            for page in doc.pages:
                if not page.blocks:
                    continue

                # Пропускаем страницы где уже есть штамп
                has_stamp = any(
                    getattr(b, "category_code", None) == "stamp" for b in page.blocks
                )
                if has_stamp:
                    continue

                # Найти блок в правом нижнем углу
                best_block = None
                best_score = -1

                for block in page.blocks:
                    x1, y1, x2, y2 = block.coords_norm
                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2

                    if cx > 0.5 and cy > 0.7:
                        score = cx + cy
                        if score > best_score:
                            best_score = score
                            best_block = block

                if best_block:
                    best_block.block_type = BlockType.IMAGE
                    best_block.category_code = "stamp"
                    if stamp_category_id:
                        best_block.category_id = stamp_category_id
                    modified_count += 1

            if modified_count == 0:
                QMessageBox.information(self._widget, "Результат", "Штампы не найдены")
                return

            # Сохранить аннотацию обратно в R2
            updated_json = json.dumps(doc.to_dict(), ensure_ascii=False, indent=2)
            if not r2.upload_text(updated_json, ann_r2_key):
                QMessageBox.critical(
                    self._widget, "Ошибка", "Не удалось сохранить аннотацию"
                )
                return

            self._widget.status_label.setText(f"🔖 Назначено штампов: {modified_count}")
            QMessageBox.information(
                self._widget, "Успех", f"Штамп назначен на {modified_count} страницах"
            )

            self._widget.annotation_replaced.emit(r2_key)

        except Exception as e:
            logger.error(f"Detect stamps failed: {e}")
            QMessageBox.critical(
                self._widget, "Ошибка", f"Ошибка определения штампов:\n{e}"
            )

    def _check_locked(self, node: TreeNode) -> bool:
        """Проверить заблокирован ли документ"""
        if node.node_type == NodeType.DOCUMENT and node.is_locked:
            QMessageBox.warning(
                self._widget,
                "Документ заблокирован",
                "Этот документ заблокирован от изменений.\nСначала снимите блокировку.",
            )
            return True
        return False

    def _update_pdf_status(self, node: TreeNode, r2_key: str, r2) -> None:
        """Обновить статус PDF после изменения аннотации"""
        from rd_core.pdf_status import calculate_pdf_status
        from app.gui.tree_node_operations import NODE_ICONS

        status, message = calculate_pdf_status(r2, node.id, r2_key)
        self._widget.client.update_pdf_status(node.id, status.value, message)

        # Обновляем отображение в дереве
        item = self._widget._node_map.get(node.id)
        if item and node.node_type == NodeType.DOCUMENT:
            node.pdf_status = status.value
            node.pdf_status_message = message

            icon = NODE_ICONS.get(node.node_type, "📄")
            status_icon = self._widget._pdf_status_manager.get_status_icon(status.value)
            lock_icon = "🔒" if node.is_locked else ""
            version_tag = f"[v{node.version}]" if node.version else "[v1]"

            display_name = f"{icon} {node.name} {lock_icon} {status_icon}".strip()
            item.setText(0, display_name)
            item.setData(0, Qt.UserRole + 1, version_tag)
            if message:
                item.setToolTip(0, message)
