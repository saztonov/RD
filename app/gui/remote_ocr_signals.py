"""
Сигналы для Remote OCR панели.

DEPRECATED: Этот модуль перемещён в app.gui.remote_ocr.signals.
Этот файл сохранён для обратной совместимости.
"""
# Реэкспорт из нового модуля
from app.gui.remote_ocr.signals import WorkerSignals

__all__ = ["WorkerSignals"]
