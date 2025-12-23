"""
Миксин для работы с файлами (открытие, сохранение, загрузка)
"""

import logging
import copy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import QTimer
from rd_core.models import Document, Page
from rd_core.pdf_utils import PDFDocument
from rd_core.annotation_io import AnnotationIO
from app.gui.file_transfer_worker import FileTransferWorker, TransferTask, TransferType

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)


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
    _auto_save_timer: QTimer = None
    _pending_save: bool = False
    _annotation_synced: bool = False  # Флаг: аннотация уже синхронизирована с R2
    _active_downloads: set = None  # Активные загрузки (защита от дублей)
    
    def _register_node_file(
        self, node_id: str, file_type: str, r2_key: str, 
        file_name: str, file_size: int = 0, mime_type: str = None
    ):
        """Регистрация файла в таблице node_files"""
        try:
            from app.tree_client import TreeClient, FileType
            client = TreeClient()
            
            ft = FileType(file_type) if file_type in [e.value for e in FileType] else FileType.PDF
            mt = mime_type or self._guess_mime_type(file_name)
            
            client.upsert_node_file(
                node_id=node_id,
                file_type=ft,
                r2_key=r2_key,
                file_name=file_name,
                file_size=file_size,
                mime_type=mt,
            )
            logger.debug(f"Registered node file: {file_type} -> {r2_key}")
        except Exception as e:
            logger.error(f"Failed to register node file: {e}")
    
    def _guess_mime_type(self, filename: str) -> str:
        """Определить MIME тип по расширению"""
        ext = Path(filename).suffix.lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".json": "application/json",
            ".md": "text/markdown",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".zip": "application/zip",
        }
        return mime_map.get(ext, "application/octet-stream")
    
    def _auto_save_annotation(self):
        """Авто-сохранение разметки при изменении блоков"""
        if not self.annotation_document or not self._current_pdf_path:
            return
        
        self._pending_save = True
        
        if self._auto_save_timer is None:
            self._auto_save_timer = QTimer(self)
            self._auto_save_timer.setSingleShot(True)
            self._auto_save_timer.timeout.connect(self._do_auto_save)
        
        # Если аннотация ещё не синхронизирована - сохранить сразу (через 100мс для debounce)
        # Иначе - через 5 секунд для накопления изменений
        if not self._annotation_synced:
            delay = 100  # Первое сохранение - почти сразу
        else:
            delay = 5000  # Последующие - через 5 секунд
        
        # Перезапускаем таймер (debounce)
        if self._auto_save_timer.isActive():
            self._auto_save_timer.stop()
        self._auto_save_timer.start(delay)
    
    def _do_auto_save(self):
        """Выполнить отложенное сохранение в фоновом потоке"""
        if not self._pending_save:
            return
        if not self.annotation_document or not self._current_pdf_path:
            return
        
        self._pending_save = False
        
        # Копируем данные для фонового потока
        ann_path = str(get_annotation_path(self._current_pdf_path))
        doc_copy = copy.deepcopy(self.annotation_document)
        r2_key = self._current_r2_key if hasattr(self, '_current_r2_key') else ""
        node_id = self._current_node_id if hasattr(self, '_current_node_id') else ""
        
        # Сохраняем в фоновом потоке
        _executor.submit(self._background_save, ann_path, doc_copy, r2_key, node_id)
    
    def _background_save(self, ann_path: str, doc: Document, r2_key: str, node_id: str):
        """Фоновое сохранение (не блокирует UI)"""
        try:
            AnnotationIO.save_annotation(doc, ann_path)
            logger.debug(f"Annotation auto-saved: {ann_path}")
            
            if r2_key:
                self._background_sync_r2(ann_path, r2_key, node_id)
        except Exception as e:
            logger.error(f"Auto-save annotation failed: {e}")
    
    def _background_sync_r2(self, ann_path: str, r2_key: str, node_id: str):
        """Фоновая синхронизация с R2"""
        try:
            from rd_core.r2_storage import R2Storage
            from pathlib import Path
            r2 = R2Storage()
            ann_r2_key = get_annotation_r2_key(r2_key)
            r2.upload_file(ann_path, ann_r2_key)
            logger.debug(f"Annotation synced to R2: {ann_r2_key}")
            
            # Помечаем что аннотация синхронизирована
            self._annotation_synced = True
            
            # Записываем файл в БД node_files и обновляем флаг has_annotation
            if node_id:
                self._register_node_file(
                    node_id, "annotation", ann_r2_key, 
                    Path(ann_path).name, Path(ann_path).stat().st_size
                )
                # Обновляем флаг has_annotation в узле
                try:
                    from app.tree_client import TreeClient
                    client = TreeClient()
                    node = client.get_node(node_id)
                    if node and not node.attributes.get("has_annotation"):
                        attrs = node.attributes.copy()
                        attrs["has_annotation"] = True
                        client.update_node(node_id, attributes=attrs)
                        # Обновляем UI в главном потоке (lambda с default для захвата значения)
                        QTimer.singleShot(0, lambda nid=node_id: self._update_tree_annotation_icon(nid))
                except Exception as e2:
                    logger.debug(f"Update has_annotation in background failed: {e2}")
        except Exception as e:
            logger.error(f"Sync annotation to R2 failed: {e}")
    
    def _flush_pending_save(self):
        """Принудительно сохранить несохранённые изменения"""
        if self._auto_save_timer and self._auto_save_timer.isActive():
            self._auto_save_timer.stop()
        if self._pending_save:
            self._do_auto_save()
    
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
    
    def _update_tree_annotation_icon(self, node_id: str):
        """Обновить иконку аннотации в дереве (вызывается из главного потока)"""
        if not hasattr(self, 'project_tree') or not self.project_tree:
            return
        
        try:
            from app.gui.tree_node_operations import NODE_ICONS
            from app.tree_client import TreeClient
            from PySide6.QtCore import Qt
            
            item = self.project_tree._node_map.get(node_id)
            if item:
                node = item.data(0, Qt.UserRole)
                if node and hasattr(node, 'attributes'):
                    node.attributes["has_annotation"] = True
                    item.setData(0, Qt.UserRole, node)
                    icon = NODE_ICONS.get(node.node_type, "📄")
                    version_tag = f"[v{node.version}]" if node.version else "[v1]"
                    display_name = f"{icon} {version_tag} {node.name} 📋"
                    item.setText(0, display_name)
        except Exception as e:
            logger.debug(f"Update tree annotation icon failed: {e}")
    
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
        
        # Обновляем заголовок
        self.setWindowTitle(f"PDF Annotation Tool - {Path(pdf_path).name}")
    
    def _on_tree_file_uploaded_r2(self, node_id: str, r2_key: str):
        """Открыть загруженный файл из R2 в редакторе"""
        self._on_tree_document_selected(node_id, r2_key)
    
    def _on_tree_document_selected(self, node_id: str, r2_key: str):
        """Открыть документ из дерева (асинхронное скачивание из R2)"""
        from app.gui.folder_settings_dialog import get_projects_dir
        
        if not r2_key:
            return
        
        # Инициализация set для отслеживания активных загрузок
        if self._active_downloads is None:
            self._active_downloads = set()
        
        # Защита от дублирующихся загрузок
        if r2_key in self._active_downloads:
            logger.debug(f"Download already in progress: {r2_key}")
            return
        
        projects_dir = get_projects_dir()
        if not projects_dir:
            QMessageBox.warning(self, "Ошибка", "Папка проектов не задана в настройках")
            return
        
        # Формируем локальный путь
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/"):]
        else:
            rel_path = r2_key
        
        local_path = Path(projects_dir) / "cache" / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Если файл уже есть - открываем сразу
        if local_path.exists():
            self._current_r2_key = r2_key
            self._current_node_id = node_id
            self._open_pdf_file(str(local_path), r2_key=r2_key)
            if node_id and hasattr(self, 'project_tree_widget'):
                self.project_tree_widget.highlight_document(node_id)
            return
        
        # Помечаем загрузку как активную
        self._active_downloads.add(r2_key)
        
        # Собираем список файлов для скачивания
        tasks = self._build_download_tasks(node_id, r2_key, str(local_path), projects_dir)
        
        # Сохраняем данные для открытия после завершения загрузки
        self._pending_download_node_id = node_id
        self._pending_download_r2_key = r2_key
        self._pending_download_local_path = str(local_path)
        self._download_errors = []
        
        # Показываем модальное окно загрузки
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt
        self._download_dialog = QProgressDialog(
            f"Загрузка документа и связанных файлов...",
            None,  # Без кнопки отмены
            0, len(tasks),
            self
        )
        self._download_dialog.setWindowTitle("Загрузка")
        self._download_dialog.setWindowModality(Qt.WindowModal)
        self._download_dialog.setMinimumDuration(0)
        self._download_dialog.setValue(0)
        self._download_dialog.show()
        
        # Асинхронное скачивание
        self._download_worker = FileTransferWorker(self)
        
        for task in tasks:
            self._download_worker.add_task(task)
        
        # Подключаем сигналы
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished_task.connect(self._on_download_task_result)
        self._download_worker.all_finished.connect(self._on_all_downloads_finished)
        
        # Запускаем
        logger.info(f"Starting async download: {r2_key} -> {local_path} ({len(tasks)} files)")
        self._download_worker.start()
    
    def _build_download_tasks(self, node_id: str, r2_key: str, local_path: str, projects_dir: str) -> list:
        """Собрать список задач для скачивания (PDF + полный пакет если распознано)"""
        from app.tree_client import TreeClient, FileType
        from pathlib import PurePosixPath
        
        tasks = []
        
        # Основной PDF
        tasks.append(TransferTask(
            transfer_type=TransferType.DOWNLOAD,
            local_path=local_path,
            r2_key=r2_key,
            node_id=node_id,
        ))
        
        # Проверяем есть ли дополнительные файлы (аннотации, markdown, кропы)
        try:
            client = TreeClient()
            node_files = client.get_node_files(node_id)
            
            for nf in node_files:
                # Пропускаем сам PDF
                if nf.file_type == FileType.PDF:
                    continue
                
                # Формируем локальный путь для файла
                if nf.r2_key.startswith("tree_docs/"):
                    rel = nf.r2_key[len("tree_docs/"):]
                else:
                    rel = nf.r2_key
                
                file_local_path = Path(projects_dir) / "cache" / rel
                file_local_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Не скачиваем если уже есть
                if file_local_path.exists():
                    continue
                
                tasks.append(TransferTask(
                    transfer_type=TransferType.DOWNLOAD,
                    local_path=str(file_local_path),
                    r2_key=nf.r2_key,
                    node_id=node_id,
                ))
            
            # Также пробуем скачать кропы из папки crops/
            pdf_stem = Path(local_path).stem
            r2_prefix = str(PurePosixPath(r2_key).parent)
            crops_prefix = f"{r2_prefix}/crops/{pdf_stem}/"
            
            from rd_core.r2_storage import R2Storage
            r2 = R2Storage()
            crop_keys = r2.list_files(crops_prefix)
            
            for crop_key in crop_keys:
                if crop_key.startswith("tree_docs/"):
                    rel = crop_key[len("tree_docs/"):]
                else:
                    rel = crop_key
                
                crop_local = Path(projects_dir) / "cache" / rel
                crop_local.parent.mkdir(parents=True, exist_ok=True)
                
                if crop_local.exists():
                    continue
                
                tasks.append(TransferTask(
                    transfer_type=TransferType.DOWNLOAD,
                    local_path=str(crop_local),
                    r2_key=crop_key,
                    node_id=node_id,
                ))
                
        except Exception as e:
            logger.warning(f"Failed to get additional files for download: {e}")
        
        return tasks
    
    def _on_download_progress(self, message: str, current: int, total: int):
        """Обновление прогресса загрузки"""
        if hasattr(self, '_download_dialog') and self._download_dialog:
            self._download_dialog.setLabelText(message)
            self._download_dialog.setValue(current)
        self.show_transfer_progress(message, current, total)
    
    def _on_download_task_result(self, task: TransferTask, success: bool, error: str):
        """Сохранение результата загрузки файла (без открытия)"""
        if not success:
            if hasattr(self, '_download_errors'):
                self._download_errors.append(f"{task.r2_key}: {error}")
            logger.error(f"Download failed: {task.r2_key} - {error}")
        else:
            logger.info(f"File downloaded from R2: {task.r2_key}")
    
    def _on_all_downloads_finished(self):
        """Все загрузки завершены - открываем PDF"""
        # Закрываем диалог прогресса
        if hasattr(self, '_download_dialog') and self._download_dialog:
            self._download_dialog.close()
            self._download_dialog = None
        
        self.hide_transfer_progress()
        
        # Убираем из активных загрузок
        if self._active_downloads and hasattr(self, '_pending_download_r2_key'):
            self._active_downloads.discard(self._pending_download_r2_key)
        
        # Проверяем ошибки
        if hasattr(self, '_download_errors') and self._download_errors:
            # Показываем ошибки только для основного PDF
            main_pdf_error = None
            for err in self._download_errors:
                if hasattr(self, '_pending_download_r2_key') and self._pending_download_r2_key in err:
                    main_pdf_error = err
                    break
            
            if main_pdf_error:
                QMessageBox.critical(self, "Ошибка", f"Не удалось скачать PDF:\n{main_pdf_error}")
                self._download_worker = None
                return
            else:
                # Ошибки только для доп. файлов - логируем, но продолжаем
                logger.warning(f"Some files failed to download: {self._download_errors}")
        
        # Открываем основной PDF
        if hasattr(self, '_pending_download_local_path') and Path(self._pending_download_local_path).exists():
            self._current_r2_key = self._pending_download_r2_key
            self._current_node_id = self._pending_download_node_id
            self._open_pdf_file(self._pending_download_local_path, r2_key=self._pending_download_r2_key)
            
            # Подсветить документ в дереве
            if self._pending_download_node_id and hasattr(self, 'project_tree_widget'):
                self.project_tree_widget.highlight_document(self._pending_download_node_id)
        
        self._download_worker = None
    
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
    
    def _on_annotation_replaced(self, r2_key: str):
        """Обработчик замены аннотации в дереве проектов"""
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
            
            # Загружаем аннотацию
            loaded_doc = AnnotationIO.load_annotation(str(ann_path))
            if not loaded_doc:
                return
            
            # Заменяем текущую аннотацию
            self.annotation_document = loaded_doc
            self._annotation_synced = True
            
            # Обновляем отображение
            self._render_current_page()
            if hasattr(self, 'blocks_tree_manager') and self.blocks_tree_manager:
                self.blocks_tree_manager.update_blocks_tree()
            
            logger.info(f"Аннотация обновлена из R2: {ann_r2_key}")
            from app.gui.toast import show_toast
            show_toast(self, "Аннотация обновлена")
            
        except Exception as e:
            logger.error(f"Ошибка обновления аннотации: {e}")