"""Миксин сверки R2/Supabase для MainWindow."""

import logging

from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class ReconciliationMixin:
    """Операции сверки файлов между R2 и Supabase."""

    def _start_r2_reconciliation(self):
        """Запустить сверку R2/Supabase для всех документов"""
        from app.gui.project_tree.reconciliation_manager import (
            get_reconciliation_manager,
        )
        from app.tree_client import NodeType

        if not hasattr(self, "project_tree") or not self.project_tree:
            return

        # Собираем все документы из дерева
        documents = []

        def collect_documents(item):
            node = item.data(0, Qt.UserRole)
            if hasattr(node, "node_type") and node.node_type == NodeType.DOCUMENT:
                r2_key = node.attributes.get("r2_key", "")
                if r2_key:
                    documents.append({"node_id": node.id, "r2_key": r2_key})
            for i in range(item.childCount()):
                collect_documents(item.child(i))

        for i in range(self.project_tree.tree.topLevelItemCount()):
            collect_documents(self.project_tree.tree.topLevelItem(i))

        if not documents:
            self._status_label.setText("Нет документов для сверки")
            return

        # Инициализируем менеджер и запускаем сверку
        recon_manager = get_reconciliation_manager(self.project_tree.client)
        recon_manager.reconciliation_started.connect(self._on_reconciliation_started)
        recon_manager.reconciliation_progress.connect(self._on_reconciliation_progress)
        recon_manager.reconciliation_finished.connect(self._on_reconciliation_finished)
        recon_manager.status_changed.connect(self._on_reconciliation_status_changed)

        recon_manager.start_reconciliation(documents)

    def _on_reconciliation_started(self):
        """Обработать начало сверки"""
        self._status_label.setText("Сверка R2/Supabase...")
        self._status_progress.setValue(0)
        self._status_progress.show()
        if hasattr(self, "hide_reconcile_action"):
            self.hide_reconcile_action.setEnabled(False)

    def _on_reconciliation_progress(self, current: int, total: int):
        """Обработать прогресс сверки"""
        self._status_progress.setMaximum(total)
        self._status_progress.setValue(current)
        self._status_label.setText(f"Сверка: {current}/{total}")

    def _on_reconciliation_finished(self):
        """Обработать завершение сверки"""
        self._status_progress.hide()
        self._status_label.setText("Сверка завершена")
        if hasattr(self, "hide_reconcile_action"):
            self.hide_reconcile_action.setEnabled(True)
        # Обновляем иконки в дереве без полной перезагрузки
        if hasattr(self, "project_tree") and self.project_tree:
            self.project_tree._refresh_visible_items()

    def _on_reconciliation_status_changed(self, node_id: str, status: str):
        """Обработать изменение статуса документа"""
        pass

    def _hide_reconciliation_status(self):
        """Скрыть результаты сверки"""
        from app.gui.project_tree.reconciliation_manager import (
            get_reconciliation_manager,
        )

        try:
            recon_manager = get_reconciliation_manager()
            recon_manager.clear_statuses()
            if hasattr(self, "hide_reconcile_action"):
                self.hide_reconcile_action.setEnabled(False)
            # Обновляем иконки без полной перезагрузки
            if hasattr(self, "project_tree") and self.project_tree:
                self.project_tree._refresh_visible_items()
            self._status_label.setText("Результаты сверки скрыты")
        except (ValueError, Exception):
            pass
