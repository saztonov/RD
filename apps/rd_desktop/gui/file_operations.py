"""
Миксин для работы с файлами (открытие, сохранение, загрузка)
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from apps.rd_desktop.gui.file_auto_save import (
    FileAutoSaveMixin,
    get_annotation_path,
    get_annotation_r2_key,
)
from apps.rd_desktop.gui.file_download import FileDownloadMixin
from apps.rd_desktop.gui.r2_operation_worker import (
    R2Operation,
    R2OperationType,
    R2OperationWorker,
)
from rd_domain.annotation import AnnotationIO
from rd_domain.models import Document, Page
from rd_pipeline.pdf import PDFDocument

logger = logging.getLogger(__name__)

# Импорт метаданных продукта
try:
    from rd_domain.metadata import __product__
except ImportError:
    __product__ = "Core Structure"

# Re-export для обратной совместимости
__all__ = ["FileOperationsMixin", "get_annotation_path", "get_annotation_r2_key"]


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
            from rd_adapters.storage import R2SyncStorage as R2Storage

            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(self._current_r2_key)
            success = r2.upload_file(str(ann_path), ann_r2_key)
            
            if success:
                logger.debug(f"Annotation synced to R2: {ann_r2_key}")
                # Обновить атрибут has_annotation в дереве
                self._update_has_annotation_flag(True)
            else:
                # Проверяем статус соединения
                if hasattr(self, 'connection_manager') and not self.connection_manager.is_connected():
                    logger.info(f"Аннотация будет синхронизирована при восстановлении соединения")
                    from apps.rd_desktop.gui.toast import show_toast
                    show_toast(self, "Аннотация сохранена локально. Синхронизация при восстановлении связи.", duration=3000)
                else:
                    logger.warning(f"Не удалось синхронизировать аннотацию: {ann_r2_key}")
        except Exception as e:
            logger.error(f"Sync annotation to R2 failed: {e}")

    def _update_has_annotation_flag(self, has_annotation: bool):
        """Обновить флаг has_annotation в узле дерева"""
        if not hasattr(self, "_current_node_id") or not self._current_node_id:
            return

        try:
            from apps.rd_desktop.tree_client import TreeClient
            from rd_pipeline.pdf import PDFStatus, calculate_pdf_status
            from rd_adapters.storage import R2SyncStorage as R2Storage

            client = TreeClient()
            node = client.get_node(self._current_node_id)
            if node:
                attrs = node.attributes.copy()
                attrs["has_annotation"] = has_annotation
                client.update_node(self._current_node_id, attributes=attrs)

                # Обновляем статус PDF в БД (кеш будет инвалидирован)
                if node.node_type.value == "document" and self._current_r2_key:
                    r2 = R2Storage()
                    status, message = calculate_pdf_status(
                        r2, self._current_node_id, self._current_r2_key
                    )
                    client.update_pdf_status(
                        self._current_node_id, status.value, message
                    )

                    # Обновляем только конкретный узел в дереве (без полного refresh)
                    if hasattr(self, "project_tree") and self.project_tree:
                        item = self.project_tree._node_map.get(self._current_node_id)
                        if item:
                            node.pdf_status = status.value
                            node.pdf_status_message = message

                            from apps.rd_desktop.gui.tree_node_operations import NODE_ICONS

                            icon = NODE_ICONS.get(node.node_type, "📄")
                            status_icon = self.project_tree._get_pdf_status_icon(
                                status.value
                            )
                            lock_icon = "🔒" if node.is_locked else ""
                            version_tag = (
                                f"[v{node.version}]" if node.version else "[v1]"
                            )

                            display_name = (
                                f"{icon} {node.name} {lock_icon} {status_icon}".strip()
                            )
                            item.setText(0, display_name)
                            item.setData(0, Qt.UserRole + 1, version_tag)
                            if message:
                                item.setToolTip(0, message)
        except Exception as e:
            logger.debug(f"Update has_annotation failed: {e}")

    def _load_annotation_if_exists(self, pdf_path: str, r2_key: str = ""):
        """Загрузить блоки - сначала из БД, потом миграция из файла

        Порядок загрузки:
        1. Если есть node_id - пробуем загрузить из БД
        2. Если в БД пусто - проверяем annotation.json (локально или R2)
        3. Если есть annotation.json - мигрируем в БД и предлагаем удалить файл
        """
        from apps.rd_desktop.gui.toast import show_toast

        # === 1. Пробуем загрузить из БД ===
        if self._current_node_id and self._use_db_sync:
            # Инициализируем sync manager
            self._set_document_for_sync(self._current_node_id)

            if self._blocks_sync_manager and self._blocks_sync_manager.has_blocks(self._current_node_id):
                # Блоки есть в БД - загружаем
                blocks = self._blocks_sync_manager.load_blocks(self._current_node_id)
                if blocks:
                    self.annotation_document = self._create_empty_annotation(pdf_path)
                    self._populate_document_from_blocks(blocks)
                    self._annotation_synced = True
                    logger.info(f"Loaded {len(blocks)} blocks from DB for {self._current_node_id}")
                    return True

        # === 2. Проверяем annotation.json ===
        ann_path = get_annotation_path(pdf_path)

        # Попробовать скачать из R2 если нет локально
        if not ann_path.exists() and r2_key:
            # Проверяем офлайн режим
            if hasattr(self, 'connection_manager') and not self.connection_manager.is_connected():
                logger.info("Не удалось скачать аннотацию - работа в офлайн режиме")
                show_toast(self, "Работа в офлайн режиме. Аннотация недоступна.", duration=3000)
            else:
                # Запускаем асинхронную загрузку
                ann_r2_key = get_annotation_r2_key(r2_key)
                self._start_async_annotation_download(pdf_path, r2_key, ann_r2_key, str(ann_path))

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
                    QMessageBox.Yes,
                )

                if reply == QMessageBox.Yes:
                    try:
                        ann_path.unlink()
                    except Exception:
                        pass
                    show_toast(self, "Создана новая разметка", success=True)
                    return False
                else:
                    return False

            if loaded:
                self.annotation_document = loaded
                logger.info(f"Annotation loaded from file: {ann_path}")

                # === 3. Миграция в БД ===
                if self._current_node_id and self._use_db_sync and self._blocks_sync_manager:
                    all_blocks = []
                    for page in loaded.pages:
                        all_blocks.extend(page.blocks)

                    if all_blocks:
                        success = self._blocks_sync_manager.sync_all_blocks(all_blocks)
                        if success:
                            logger.info(f"Migrated {len(all_blocks)} blocks to DB")
                            # Предлагаем удалить старую аннотацию
                            self._offer_delete_legacy_annotation(ann_path, r2_key)
                        else:
                            logger.warning("Failed to migrate blocks to DB, using file fallback")
                            # Fallback - используем старый кеш
                            from apps.rd_desktop.gui.annotation_cache import get_annotation_cache
                            cache = get_annotation_cache()
                            cache.set(
                                self._current_node_id,
                                self.annotation_document,
                                pdf_path,
                                r2_key,
                                str(ann_path)
                            )
                else:
                    # Нет node_id - используем старый кеш
                    if self._current_node_id:
                        from apps.rd_desktop.gui.annotation_cache import get_annotation_cache
                        cache = get_annotation_cache()
                        cache.set(
                            self._current_node_id,
                            self.annotation_document,
                            pdf_path,
                            r2_key,
                            str(ann_path)
                        )

                # Миграция формата выполнена - сохраняем
                if result.migrated and not (self._use_db_sync and self._blocks_sync_manager):
                    logger.info(f"Annotation format migrated, saving")
                    AnnotationIO.save_annotation(loaded, str(ann_path))
                    self._sync_annotation_to_r2()

                    warn_count = len(result.warnings)
                    if warn_count > 0:
                        show_toast(
                            self,
                            f"Разметка обновлена до актуального формата ({warn_count} изм.)",
                            duration=3000,
                            success=True,
                        )
                    else:
                        show_toast(self, "Формат разметки обновлён", success=True)

                self._annotation_synced = True
                self._update_has_annotation_flag(True)
                return True
        return False

    def _populate_document_from_blocks(self, blocks):
        """Заполнить annotation_document блоками из БД"""
        if not self.annotation_document:
            return

        for block in blocks:
            if block.page_index < len(self.annotation_document.pages):
                page = self.annotation_document.pages[block.page_index]
                page.blocks.append(block)

    def _offer_delete_legacy_annotation(self, local_path: Path, r2_key: str):
        """Предложить удалить annotation.json после миграции в БД"""
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QTimer

        def show_dialog():
            msg = QMessageBox(self)
            msg.setWindowTitle("Миграция завершена")
            msg.setText("Блоки успешно перенесены в базу данных.")
            msg.setInformativeText(
                "Файл аннотации (annotation.json) больше не нужен.\n"
                "Удалить его из R2 и локальной папки?"
            )
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.Yes)

            if msg.exec() == QMessageBox.Yes:
                self._delete_legacy_annotation(local_path, r2_key)

        # Показываем диалог с небольшой задержкой
        QTimer.singleShot(500, show_dialog)

    def _delete_legacy_annotation(self, local_path: Path, r2_key: str):
        """Удалить annotation.json из всех мест"""
        from apps.rd_desktop.gui.toast import show_toast

        deleted_count = 0

        # 1. Удалить локально
        if local_path.exists():
            try:
                local_path.unlink()
                logger.info(f"Deleted local annotation: {local_path}")
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete local annotation: {e}")

        # 2. Удалить из R2
        if r2_key:
            ann_r2_key = get_annotation_r2_key(r2_key)
            try:
                from rd_adapters.storage import R2SyncStorage
                r2 = R2SyncStorage()
                r2.delete_file(ann_r2_key)
                logger.info(f"Deleted R2 annotation: {ann_r2_key}")
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete R2 annotation: {e}")

        # 3. Удалить запись из node_files (Supabase)
        if self._current_node_id:
            try:
                from apps.rd_desktop.tree_client import TreeClient
                client = TreeClient()
                client.delete_node_file(self._current_node_id, file_type="annotation")
                logger.info(f"Deleted node_files annotation record")
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete node_files record: {e}")

        if deleted_count > 0:
            show_toast(self, "Старая аннотация удалена", duration=2000, success=True)

    def _start_async_annotation_download(
        self, pdf_path: str, r2_key: str, ann_r2_key: str, ann_path: str
    ):
        """Запустить асинхронную загрузку аннотации из R2"""
        # Показываем индикатор загрузки
        if hasattr(self, 'show_transfer_progress'):
            self.show_transfer_progress("Загрузка аннотации...", 0, 1)

        # Создаём worker для загрузки
        self._ann_download_worker = R2OperationWorker()
        self._ann_download_worker.add_operation(R2Operation(
            operation_type=R2OperationType.DOWNLOAD_FILE,
            remote_key=ann_r2_key,
            local_path=ann_path,
            callback_data={
                "pdf_path": pdf_path,
                "r2_key": r2_key,
                "ann_path": ann_path,
            }
        ))

        # Подключаем callback
        self._ann_download_worker.signals.operation_completed.connect(
            self._on_annotation_download_completed
        )
        self._ann_download_worker.start()

    def _on_annotation_download_completed(self, op, success: bool, result, error: str):
        """Callback после загрузки аннотации из R2"""
        from apps.rd_desktop.gui.toast import show_toast

        # Скрываем индикатор
        if hasattr(self, 'hide_transfer_progress'):
            self.hide_transfer_progress()

        callback_data = op.callback_data
        pdf_path = callback_data.get("pdf_path")
        r2_key = callback_data.get("r2_key")
        ann_path = callback_data.get("ann_path")

        if success and Path(ann_path).exists():
            # Загружаем скачанную аннотацию
            loaded, migrate_result = AnnotationIO.load_and_migrate(ann_path)

            if loaded and migrate_result.success:
                self.annotation_document = loaded
                logger.info(f"Annotation loaded from R2: {ann_path}")

                # Инициализируем кеш аннотаций
                if self._current_node_id:
                    from apps.rd_desktop.gui.annotation_cache import get_annotation_cache
                    cache = get_annotation_cache()
                    cache.set(
                        self._current_node_id,
                        self.annotation_document,
                        pdf_path,
                        r2_key,
                        ann_path
                    )

                # Миграция формата - сохраняем
                if migrate_result.migrated:
                    AnnotationIO.save_annotation(loaded, ann_path)
                    self._sync_annotation_to_r2()
                    show_toast(self, "Формат разметки обновлён", success=True)

                self._annotation_synced = True
                self._update_has_annotation_flag(True)

                # Обновляем отображение
                self._render_current_page()
                if hasattr(self, "blocks_tree_manager") and self.blocks_tree_manager:
                    self.blocks_tree_manager.update_blocks_tree()
        else:
            logger.debug(f"Annotation not found in R2 or download failed: {error}")

        # Очищаем worker
        self._ann_download_worker = None

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
        self._page_images_order.clear()
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
        if hasattr(self, "_update_groups_tree"):
            self._update_groups_tree()

        # Загружаем OCR result file для preview
        if hasattr(self, "_load_ocr_result_file"):
            self._load_ocr_result_file()

        # Обновляем заголовок
        self.setWindowTitle(f"{__product__} - {Path(pdf_path).name}")

    def _save_annotation(self):
        """Сохранить разметку в JSON"""
        if not self.annotation_document:
            return

        # Определяем путь по умолчанию рядом с PDF
        default_path = ""
        if hasattr(self, "_current_pdf_path") and self._current_pdf_path:
            pdf_path = Path(self._current_pdf_path)
            default_path = str(pdf_path.parent / f"{pdf_path.stem}_annotation.json")

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить разметку", default_path, "JSON Files (*.json)"
        )
        if file_path:
            AnnotationIO.save_annotation(self.annotation_document, file_path)
            from apps.rd_desktop.gui.toast import show_toast

            show_toast(self, "Разметка сохранена")

    def _load_annotation(self):
        """Загрузить разметку из JSON"""
        from apps.rd_desktop.gui.toast import show_toast

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить разметку", "", "JSON Files (*.json)"
        )
        if not file_path:
            return

        loaded_doc, result = AnnotationIO.load_and_migrate(file_path)

        if not result.success:
            error_msg = "; ".join(result.errors)
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось загрузить разметку:\n{error_msg}"
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
        """Обработчик замены аннотации в дереве проектов (асинхронно)"""
        # Проверяем совпадает ли r2_key с текущим открытым документом
        if not hasattr(self, "_current_r2_key") or self._current_r2_key != r2_key:
            return

        if not self._current_pdf_path:
            return

        ann_r2_key = get_annotation_r2_key(r2_key)
        ann_path = get_annotation_path(self._current_pdf_path)

        # Запускаем асинхронную загрузку
        self._ann_replace_worker = R2OperationWorker()
        self._ann_replace_worker.add_operation(R2Operation(
            operation_type=R2OperationType.DOWNLOAD_FILE,
            remote_key=ann_r2_key,
            local_path=str(ann_path),
            callback_data={
                "r2_key": r2_key,
                "ann_path": str(ann_path),
            }
        ))
        self._ann_replace_worker.signals.operation_completed.connect(
            self._on_annotation_replace_downloaded
        )
        self._ann_replace_worker.start()

    def _on_annotation_replace_downloaded(self, op, success: bool, result, error: str):
        """Callback после загрузки замененной аннотации"""
        from apps.rd_desktop.gui.toast import show_toast

        callback_data = op.callback_data
        r2_key = callback_data.get("r2_key")
        ann_path = callback_data.get("ann_path")

        if not success:
            logger.warning(f"Не удалось скачать аннотацию из R2: {error}")
            self._ann_replace_worker = None
            return

        try:
            # Загружаем с миграцией
            loaded_doc, migrate_result = AnnotationIO.load_and_migrate(ann_path)
            if not migrate_result.success or not loaded_doc:
                logger.warning(f"Не удалось загрузить аннотацию: {migrate_result.errors}")
                return

            # Заменяем текущую аннотацию
            self.annotation_document = loaded_doc
            self._annotation_synced = True

            # Если была миграция - сохраняем и синхронизируем
            if migrate_result.migrated:
                AnnotationIO.save_annotation(loaded_doc, ann_path)
                self._sync_annotation_to_r2()

            # Обновляем отображение
            self._render_current_page()
            if hasattr(self, "blocks_tree_manager") and self.blocks_tree_manager:
                self.blocks_tree_manager.update_blocks_tree()
            if hasattr(self, "_update_groups_tree"):
                self._update_groups_tree()

            logger.info(f"Аннотация обновлена из R2: {op.remote_key}")
            show_toast(self, "Аннотация обновлена", success=True)

        except Exception as e:
            logger.error(f"Ошибка обновления аннотации: {e}")
        finally:
            self._ann_replace_worker = None
