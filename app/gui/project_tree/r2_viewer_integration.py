"""Интеграция с R2 Storage для просмотра файлов"""
import json
import logging
import os
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Dict, List, Optional

from PySide6.QtWidgets import QMessageBox

from app.tree_client import NodeType, TreeNode

if TYPE_CHECKING:
    from app.gui.project_tree.widget import ProjectTreeWidget

logger = logging.getLogger(__name__)

# Иконки для расширений файлов
FILE_ICONS = {
    "pdf": "📕",
    "json": "📋",
    "md": "📝",
    "png": "🖼️",
    "jpg": "🖼️",
    "jpeg": "🖼️",
    "webp": "🖼️",
    "zip": "📦",
}


class R2ViewerIntegration:
    """
    Интеграция с R2 Storage для просмотра файлов узлов.

    Отвечает за:
    - Отображение файлов на R2
    - Построение дерева файлов
    - Определение иконок файлов
    """

    def __init__(self, widget: "ProjectTreeWidget"):
        """
        Args:
            widget: Родительский виджет ProjectTreeWidget
        """
        self._widget = widget

    def _get_latest_ocr_job_id(self, node_id: str) -> Optional[str]:
        """Получить job_id последнего OCR запуска из latest_ocr_run.json"""
        from rd_core.r2_storage import R2Storage

        try:
            r2 = R2Storage()
            latest_run_key = f"tree_docs/{node_id}/latest_ocr_run.json"
            content = r2.download_text(latest_run_key)
            if content:
                data = json.loads(content)
                return data.get("job_id")
        except Exception as e:
            logger.debug(f"Failed to get latest OCR job_id: {e}")
        return None

    def view_on_r2(self, node: TreeNode) -> None:
        """Показать файлы узла на R2 Storage"""
        from app.gui.r2_files_dialog import R2FilesDialog
        from rd_core.r2_storage import R2Storage

        # Определяем r2_prefix для узла
        r2_prefix = self._get_r2_prefix(node)

        self._widget.status_label.setText("Загрузка файлов с R2...")

        try:
            r2 = R2Storage()
            r2_objects = r2.list_objects_with_metadata(r2_prefix)

            if not r2_objects:
                QMessageBox.information(
                    self._widget, "R2 Storage", f"Нет файлов в папке:\n{r2_prefix}"
                )
                self._widget.status_label.setText("")
                return

            # Преобразуем в формат для диалога
            r2_files = self._build_file_tree(r2_objects, r2_prefix)

            # Получаем публичный URL R2
            r2_base_url = os.getenv("R2_PUBLIC_URL", "https://rd1.svarovsky.ru")
            r2_base_url = f"{r2_base_url}/{r2_prefix.rstrip('/')}"

            # Определяем локальную папку
            local_folder = self._get_local_folder(node, r2_prefix)

            # Получаем ID последнего OCR запуска
            latest_job_id = self._get_latest_ocr_job_id(node.id)

            self._widget.status_label.setText("")

            dialog = R2FilesDialog(
                r2_base_url,
                r2_files,
                self._widget,
                r2_prefix=r2_prefix,
                node_id=node.id,
                local_folder=local_folder,
                latest_job_id=latest_job_id,
            )
            dialog.exec()

        except Exception as e:
            logger.error(f"Failed to list R2 files: {e}")
            self._widget.status_label.setText("")
            QMessageBox.critical(
                self._widget, "Ошибка", f"Не удалось загрузить список файлов:\n{e}"
            )

    def _get_r2_prefix(self, node: TreeNode) -> str:
        """Определить R2 префикс для узла.

        Для документов используем tree_docs/{node_id}/ чтобы видеть:
        - PDF файл (если он там)
        - OCR результаты в папке ocr_runs/{job_id}/
        - Другие связанные файлы
        """
        # Для любого типа узла используем tree_docs/{node_id}/
        # Это гарантирует отображение всех файлов включая ocr_runs/
        return f"tree_docs/{node.id}/"

    def _get_local_folder(self, node: TreeNode, r2_prefix: str):
        """Определить локальную папку для кэша"""
        from app.gui.folder_settings_dialog import get_projects_dir

        projects_dir = get_projects_dir()
        if not projects_dir:
            return None

        if node.node_type == NodeType.DOCUMENT:
            r2_key = node.attributes.get("r2_key", "")
            if r2_key:
                rel_path = (
                    r2_key[len("tree_docs/"):]
                    if r2_key.startswith("tree_docs/")
                    else r2_key
                )
                return Path(projects_dir) / "cache" / Path(rel_path).parent
            else:
                return Path(projects_dir) / "cache" / node.id
        else:
            return Path(projects_dir) / "cache" / node.id

    def _build_file_tree(self, r2_objects: List[dict], prefix: str) -> List[dict]:
        """Построить дерево файлов из списка R2 объектов"""
        folders = defaultdict(list)
        files = []

        for obj in r2_objects:
            key = obj.get("Key", "")
            if not key.startswith(prefix):
                continue

            rel_path = key[len(prefix):]
            if not rel_path:
                continue

            parts = rel_path.split("/")
            if len(parts) == 1:
                # Файл в корне
                ext = rel_path.split(".")[-1].lower() if "." in rel_path else ""
                icon = self.get_file_icon(ext)
                files.append({
                    "name": rel_path,
                    "path": key,
                    "icon": icon,
                    "is_dir": False,
                    "size": obj.get("Size", 0),
                })
            else:
                # Файл в подпапке
                folder_name = parts[0]
                folders[folder_name].append(obj)

        result = []

        # Добавляем папки
        for folder_name, folder_objects in sorted(folders.items()):
            children = self._build_file_tree(
                folder_objects, f"{prefix}{folder_name}/"
            )
            result.append({
                "name": folder_name,
                "icon": "📁",
                "is_dir": True,
                "children": children,
            })

        # Добавляем файлы
        result.extend(sorted(files, key=lambda x: x["name"]))

        return result

    @staticmethod
    def get_file_icon(ext: str) -> str:
        """Получить иконку для расширения файла"""
        return FILE_ICONS.get(ext, "📄")
