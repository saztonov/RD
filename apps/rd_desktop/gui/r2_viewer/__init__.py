"""Модуль просмотра файлов R2"""

from apps.rd_desktop.gui.r2_viewer.delete_worker import R2DeleteWorker
from apps.rd_desktop.gui.r2_viewer.dialog import R2FilesDialog
from apps.rd_desktop.gui.r2_viewer.download_worker import R2DownloadWorker

__all__ = ["R2FilesDialog", "R2DownloadWorker", "R2DeleteWorker"]
