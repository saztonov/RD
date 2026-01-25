"""
Диалог сверки файлов между R2 и Supabase.

ПРИМЕЧАНИЕ: Этот модуль перенесён в app/gui/reconciliation/ пакет.
Импорты сохранены для обратной совместимости.
"""
from __future__ import annotations

from app.gui.reconciliation import (
    DiscrepancyType,
    FileDiscrepancy,
    FileReconciliationDialog,
    ReconciliationWorker,
)

__all__ = [
    "DiscrepancyType",
    "FileDiscrepancy",
    "ReconciliationWorker",
    "FileReconciliationDialog",
]
