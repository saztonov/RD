"""
Routes для управления задачами OCR.

DEPRECATED: Этот модуль перемещён в services.remote_ocr.server.routes.jobs.
Этот файл сохранён для обратной совместимости.
"""
# Реэкспорт из нового модуля
from services.remote_ocr.server.routes.jobs import router

__all__ = ["router"]
