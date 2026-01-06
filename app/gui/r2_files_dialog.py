"""
Диалог для просмотра файлов на R2.

DEPRECATED: Этот модуль перемещён в app.gui.r2_viewer.
Этот файл сохранён для обратной совместимости.
"""
# Реэкспорт из нового модуля
from app.gui.r2_viewer import R2DeleteWorker, R2DownloadWorker, R2FilesDialog

__all__ = ["R2FilesDialog", "R2DownloadWorker", "R2DeleteWorker"]
