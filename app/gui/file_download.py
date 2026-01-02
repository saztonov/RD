"""Скачивание документов из R2"""
import logging
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QProgressDialog
from PySide6.QtCore import Qt

from app.gui.file_transfer_worker import FileTransferWorker, TransferTask, TransferType

logger = logging.getLogger(__name__)


class FileDownloadMixin:
    """Миксин для скачивания документов из R2"""
    
    _active_downloads: set = None
    
    def _update_lock_status(self, node_id: str):
        """Обновить статус блокировки документа"""
        if not node_id:
            self._current_node_locked = False
            return
        
        try:
            from app.tree_client import TreeClient
            client = TreeClient()
            if client.is_available():
                node = client.get_node(node_id)
                if node:
                    self._current_node_locked = node.is_locked
                    logger.info(f"Document lock status: {self._current_node_locked}")
                    return
        except Exception as e:
            logger.error(f"Failed to get lock status: {e}")
        
        self._current_node_locked = False
    
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
            # Проверяем блокировку документа
            self._update_lock_status(node_id)
            # Устанавливаем режим read_only в page_viewer
            if hasattr(self, 'page_viewer'):
                self.page_viewer.read_only = self._current_node_locked
            # Отключаем кнопки перемещения блоков для заблокированных документов
            if hasattr(self, 'move_block_up_btn'):
                self.move_block_up_btn.setEnabled(not self._current_node_locked)
            if hasattr(self, 'move_block_down_btn'):
                self.move_block_down_btn.setEnabled(not self._current_node_locked)
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
            # Проверяем блокировку документа
            self._update_lock_status(self._pending_download_node_id)
            # Устанавливаем режим read_only в page_viewer
            if hasattr(self, 'page_viewer'):
                self.page_viewer.read_only = self._current_node_locked
            # Отключаем кнопки перемещения блоков для заблокированных документов
            if hasattr(self, 'move_block_up_btn'):
                self.move_block_up_btn.setEnabled(not self._current_node_locked)
            if hasattr(self, 'move_block_down_btn'):
                self.move_block_down_btn.setEnabled(not self._current_node_locked)
            self._open_pdf_file(self._pending_download_local_path, r2_key=self._pending_download_r2_key)
            
            # Подсветить документ в дереве
            if self._pending_download_node_id and hasattr(self, 'project_tree_widget'):
                self.project_tree_widget.highlight_document(self._pending_download_node_id)
        
        self._download_worker = None



