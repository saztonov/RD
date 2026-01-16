"""Операции с папками документов"""
import logging
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from app.tree_client import TreeNode

logger = logging.getLogger(__name__)


class TreeFolderOperationsMixin:
    """Миксин для операций с папками документов"""

    def _open_document_folder(self, node: TreeNode):
        """Открыть папку документа в проводнике (скачать с R2 если нет локально)"""
        from pathlib import PurePosixPath

        from app.gui.folder_settings_dialog import get_projects_dir
        from rd_adapters.storage import R2SyncStorage as R2Storage

        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            QMessageBox.warning(self, "Ошибка", "R2 ключ файла не найден")
            return

        projects_dir = get_projects_dir()
        if not projects_dir:
            QMessageBox.warning(self, "Ошибка", "Папка проектов не задана в настройках")
            return

        # Определяем локальную папку (parent от PDF файла)
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/") :]
        else:
            rel_path = r2_key

        local_file = Path(projects_dir) / "cache" / rel_path
        local_folder = local_file.parent
        local_folder.mkdir(parents=True, exist_ok=True)

        # Скачиваем только PDF, аннотацию и MD (без кропов)
        self.status_label.setText("Скачивание файлов с R2...")
        try:
            r2 = R2Storage()
            r2_prefix = str(PurePosixPath(r2_key).parent)
            pdf_stem = Path(r2_key).stem

            # Список файлов для скачивания: PDF, annotation
            files_to_download = [
                (r2_key, local_file),  # PDF
                (
                    f"{r2_prefix}/{pdf_stem}_annotation.json",
                    local_folder / f"{pdf_stem}_annotation.json",
                ),
            ]

            downloaded = 0
            for remote_key, local_path in files_to_download:
                if not local_path.exists():
                    if r2.exists(remote_key):
                        if r2.download_file(remote_key, str(local_path)):
                            downloaded += 1

            self.status_label.setText(f"Скачано файлов: {downloaded}")
            logger.info(f"Downloaded {downloaded} files for document: {r2_key}")

        except Exception as e:
            logger.error(f"Failed to download files from R2: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось скачать файлы:\n{e}")
            return

        # Открываем папку в проводнике
        try:
            if sys.platform == "win32":
                subprocess.run(["explorer", str(local_folder)], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(local_folder)], check=False)
            else:
                subprocess.run(["xdg-open", str(local_folder)], check=False)

            self.status_label.setText(f"📂 {local_folder.name}")
        except Exception as e:
            logger.error(f"Failed to open folder: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть папку:\n{e}")

    def _remove_stamps_from_document(self, node: TreeNode):
        """Удалить рамки и QR-коды из PDF документа (скачать из R2, обработать, загрузить обратно)"""
        # Проверка блокировки документа
        if self._check_document_locked(node):
            return

        from app.gui.folder_settings_dialog import get_projects_dir
        from app.gui.tree_node_operations import NODE_ICONS
        from rd_core.pdf_stamp_remover import remove_stamps_from_pdf
        from rd_adapters.storage import R2SyncStorage as R2Storage

        r2_key = node.attributes.get("r2_key", "")
        if not r2_key:
            QMessageBox.warning(self, "Ошибка", "R2 ключ файла не найден")
            return

        try:
            r2 = R2Storage()
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка R2", f"Не удалось подключиться к R2:\n{e}"
            )
            return

        # Скачиваем в папку проектов (с учётом структуры папок)
        projects_dir = get_projects_dir()
        if not projects_dir:
            QMessageBox.warning(self, "Ошибка", "Папка проектов не задана в настройках")
            return

        # Сохраняем структуру папок из R2
        if r2_key.startswith("tree_docs/"):
            rel_path = r2_key[len("tree_docs/") :]
        else:
            rel_path = r2_key

        local_path = Path(projects_dir) / "cache" / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Закрываем файл если открыт в редакторе
        self._close_if_open(r2_key)

        # Если файл уже есть локально - используем его, иначе скачиваем
        if not local_path.exists():
            if not r2.download_file(r2_key, str(local_path)):
                QMessageBox.critical(
                    self, "Ошибка", f"Не удалось скачать файл из R2:\n{r2_key}"
                )
                return

        output_path = local_path.parent / f"{local_path.stem}_clean{local_path.suffix}"
        success, result = remove_stamps_from_pdf(str(local_path), str(output_path))

        if not success:
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось обработать файл:\n{result}"
            )
            return

        # Загружаем обработанный файл в R2
        parent_item = self._node_map.get(node.id)
        parent = parent_item.parent() if parent_item else None
        parent_node = parent.data(0, self._get_user_role()) if parent else None

        if not isinstance(parent_node, TreeNode):
            QMessageBox.warning(self, "Ошибка", "Не найден родительский узел")
            return

        new_r2_key = f"tree_docs/{parent_node.id}/{output_path.name}"

        # Проверка уникальности имени в папке
        if not self._check_name_unique(parent_node.id, output_path.name):
            QMessageBox.warning(
                self,
                "Ошибка",
                f"Файл с именем '{output_path.name}' уже существует в этой папке",
            )
            return

        if not r2.upload_file(str(output_path), new_r2_key):
            QMessageBox.critical(
                self, "Ошибка", "Не удалось загрузить обработанный файл в R2"
            )
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

            QMessageBox.information(
                self, "Готово", f"Рамки удалены.\nФайл: {output_path.name}"
            )
        except Exception as e:
            logger.exception(f"Error adding clean document: {e}")
            QMessageBox.warning(
                self, "Внимание", f"Файл загружен в R2, но не добавлен в дерево:\n{e}"
            )
