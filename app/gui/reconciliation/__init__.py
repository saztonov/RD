"""
Модуль сверки файлов между R2 и Supabase.

Компоненты:
- types.py - DiscrepancyType, FileDiscrepancy
- worker.py - ReconciliationWorker (QThread)
- dialog.py - FileReconciliationDialog (QDialog)
"""
from .dialog import FileReconciliationDialog
from .types import DiscrepancyType, FileDiscrepancy
from .worker import ReconciliationWorker

__all__ = [
    "DiscrepancyType",
    "FileDiscrepancy",
    "ReconciliationWorker",
    "FileReconciliationDialog",
]
