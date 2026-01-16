"""Миксин для группировки блоков"""

import logging
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QMessageBox, QTreeWidgetItem

logger = logging.getLogger(__name__)


class BlockGroupsMixin:
    """Миксин для работы с группами блоков"""

    def _update_groups_tree(self):
        """Обновить дерево групп"""
        if not hasattr(self, "groups_tree"):
            return

        # Сохраняем развёрнутые группы
        expanded_groups = set()
        for i in range(self.groups_tree.topLevelItemCount()):
            item = self.groups_tree.topLevelItem(i)
            if item.isExpanded():
                data = item.data(0, Qt.UserRole)
                if data and data.get("group_id"):
                    expanded_groups.add(data["group_id"])

        self.groups_tree.clear()

        if not self.annotation_document:
            return

        # Собираем все группы из всего документа
        groups = (
            {}
        )  # group_id -> {"name": str, "blocks": list of (page_num, block_idx, block)}
        ungrouped_count = 0

        for page in self.annotation_document.pages:
            for idx, block in enumerate(page.blocks):
                if block.group_id:
                    if block.group_id not in groups:
                        groups[block.group_id] = {
                            "name": block.group_name or "Без названия",
                            "blocks": [],
                        }
                    groups[block.group_id]["blocks"].append(
                        (page.page_number, idx, block)
                    )
                    # Обновляем название, если оно есть
                    if block.group_name:
                        groups[block.group_id]["name"] = block.group_name
                else:
                    ungrouped_count += 1

        # Добавляем "Общая группа" для блоков без группы
        if ungrouped_count > 0:
            default_item = QTreeWidgetItem(self.groups_tree)
            default_item.setText(0, "📁 Общая группа")
            default_item.setText(1, str(ungrouped_count))
            default_item.setData(0, Qt.UserRole, {"type": "group", "group_id": None})

        # Добавляем остальные группы
        for group_id, group_data in groups.items():
            group_item = QTreeWidgetItem(self.groups_tree)
            group_name = group_data["name"]
            blocks = group_data["blocks"]
            group_item.setText(0, f"📦 {group_name}")
            group_item.setText(1, str(len(blocks)))
            group_item.setData(
                0,
                Qt.UserRole,
                {"type": "group", "group_id": group_id, "group_name": group_name},
            )
            group_item.setToolTip(0, f"Блоков: {len(blocks)}")

            # Добавляем блоки как дочерние элементы
            for page_num, block_idx, block in blocks:
                block_item = QTreeWidgetItem(group_item)
                block_item.setText(0, f"Стр.{page_num + 1} Блок {block_idx + 1}")
                block_item.setText(1, block.block_type.value)
                # Колонка Категория (для IMAGE блоков)
                from rd_domain.models import BlockType

                cat_name = (
                    self._get_category_name(block.category_id)
                    if block.block_type == BlockType.IMAGE
                    else ""
                )
                block_item.setText(2, cat_name)
                block_item.setData(
                    0,
                    Qt.UserRole,
                    {
                        "type": "block",
                        "page": page_num,
                        "idx": block_idx,
                        "group_id": group_id,
                    },
                )

            # Восстанавливаем развёрнутое состояние
            if group_id in expanded_groups:
                group_item.setExpanded(True)

    def _on_groups_tree_clicked(self, item: QTreeWidgetItem, column: int):
        """Клик по элементу дерева групп"""
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        if data.get("type") == "group":
            # Выбрана группа
            group_id = data.get("group_id")
            self.selected_group_id = group_id

            if group_id:
                # Находим первый блок группы и все блоки на его странице
                first_block_info = None
                for page in self.annotation_document.pages:
                    for idx, block in enumerate(page.blocks):
                        if block.group_id == group_id:
                            if first_block_info is None:
                                first_block_info = (page.page_number, idx)
                            break
                    if first_block_info:
                        break

                if first_block_info:
                    page_num, _ = first_block_info

                    # Переходим на страницу
                    if self.current_page != page_num:
                        self.navigation_manager.save_current_zoom()

                    self.current_page = page_num
                    self.navigation_manager.load_page_image(self.current_page)
                    self.navigation_manager.restore_zoom()

                    current_page_data = self._get_or_create_page(self.current_page)
                    self.page_viewer.set_blocks(
                        current_page_data.blocks if current_page_data else []
                    )
                    self.page_viewer.fit_to_view()

                    # Выделяем все блоки группы на этой странице
                    group_indices = [
                        idx
                        for idx, block in enumerate(current_page_data.blocks)
                        if block.group_id == group_id
                    ]

                    self.page_viewer.selected_block_idx = None
                    self.page_viewer.selected_block_indices = group_indices
                    self.page_viewer._redraw_blocks()

                    self._update_ui()

            # Раскрываем группу
            item.setExpanded(not item.isExpanded())

        elif data.get("type") == "block":
            # Выбран блок внутри группы - переходим к нему
            page_num = data["page"]
            block_idx = data["idx"]

            # Сохраняем выбранную группу
            self.selected_group_id = data.get("group_id")

            if self.current_page != page_num:
                self.navigation_manager.save_current_zoom()

            self.current_page = page_num
            self.navigation_manager.load_page_image(self.current_page)
            self.navigation_manager.restore_zoom()

            current_page_data = self._get_or_create_page(self.current_page)
            self.page_viewer.set_blocks(
                current_page_data.blocks if current_page_data else []
            )
            self.page_viewer.fit_to_view()

            self.page_viewer.selected_block_idx = block_idx
            self.page_viewer.selected_block_indices = []
            self.page_viewer._redraw_blocks()

            self._update_ui()

    def _on_groups_tree_context_menu(self, position):
        """Контекстное меню для дерева групп"""
        if not hasattr(self, "groups_tree"):
            return

        item = self.groups_tree.itemAt(position)
        if not item:
            return

        data = item.data(0, Qt.UserRole)
        if not data:
            return

        menu = QMenu(self)

        if data.get("type") == "group":
            group_id = data.get("group_id")

            if group_id:  # Не для общей группы
                # Переименовать группу
                rename_action = menu.addAction("✏️ Переименовать")
                rename_action.triggered.connect(
                    lambda: self._rename_group(group_id, data.get("group_name", ""))
                )

                menu.addSeparator()

                # Удалить группу (разгруппировать)
                ungroup_action = menu.addAction("📤 Разгруппировать")
                ungroup_action.triggered.connect(lambda: self._ungroup_blocks(group_id))

                menu.addSeparator()

                # Удалить все блоки группы
                delete_action = menu.addAction("🗑️ Удалить все блоки группы")
                delete_action.triggered.connect(
                    lambda: self._delete_group_blocks(group_id)
                )

        elif data.get("type") == "block":
            # Удалить блок из группы
            remove_action = menu.addAction("📤 Убрать из группы")
            remove_action.triggered.connect(
                lambda: self._remove_block_from_group(data["page"], data["idx"])
            )

        if not menu.isEmpty():
            menu.exec_(self.groups_tree.viewport().mapToGlobal(position))

    def _group_selected_blocks(self):
        """Сгруппировать выбранные блоки (из toolbar)"""
        if not self.annotation_document:
            return

        # Получаем выбранные блоки из page_viewer
        selected_indices = self.page_viewer.selected_block_indices
        if len(selected_indices) < 2:
            # Проверяем, выбран ли хотя бы один блок
            if self.page_viewer.selected_block_idx is not None:
                from apps.rd_desktop.gui.toast import show_toast

                show_toast(self, "Выберите несколько блоков (Ctrl+клик)")
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return

        # Проверяем, есть ли выбранная группа
        group_id = getattr(self, "selected_group_id", None)
        group_name = None

        if group_id:
            # Берём название существующей группы
            for block in current_page_data.blocks:
                if block.group_id == group_id and block.group_name:
                    group_name = block.group_name
                    break
        else:
            # Показываем немодальный диалог
            from apps.rd_desktop.gui.group_name_dialog import GroupNameDialog

            dialog = GroupNameDialog(
                self,
                list(selected_indices),
                lambda data, gid, name: self._apply_group_to_blocks(data, gid, name),
            )
            dialog.show()
            return

        self._apply_group_to_blocks(list(selected_indices), group_id, group_name)

    def _apply_group_to_blocks(
        self, selected_indices: list, group_id: str, group_name: str
    ):
        """Применить группировку к блокам на текущей странице"""
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return

        self._save_undo_state()

        # Сохраняем текущий зум и позицию
        saved_transform = self.page_viewer.transform()
        saved_zoom_factor = self.page_viewer.zoom_factor
        saved_h_scroll = self.page_viewer.horizontalScrollBar().value()
        saved_v_scroll = self.page_viewer.verticalScrollBar().value()

        # Применяем group_id и group_name ко всем выбранным блокам
        for block_idx in selected_indices:
            if 0 <= block_idx < len(current_page_data.blocks):
                current_page_data.blocks[block_idx].group_id = group_id
                current_page_data.blocks[block_idx].group_name = group_name

        # Обновляем UI
        self._render_current_page()

        # Восстанавливаем зум и позицию
        self.page_viewer.setTransform(saved_transform)
        self.page_viewer.zoom_factor = saved_zoom_factor
        self.page_viewer.horizontalScrollBar().setValue(saved_h_scroll)
        self.page_viewer.verticalScrollBar().setValue(saved_v_scroll)

        self._update_groups_tree()
        self._auto_save_annotation()

        # Уведомление
        from apps.rd_desktop.gui.toast import show_toast

        show_toast(self, f"Блоки сгруппированы: {group_name}")

    def _ungroup_blocks(self, group_id: str):
        """Разгруппировать блоки (убрать группу)"""
        if not self.annotation_document or not group_id:
            return

        self._save_undo_state()

        # Сохраняем текущий зум и позицию
        saved_transform = self.page_viewer.transform()
        saved_zoom_factor = self.page_viewer.zoom_factor
        saved_h_scroll = self.page_viewer.horizontalScrollBar().value()
        saved_v_scroll = self.page_viewer.verticalScrollBar().value()

        count = 0
        for page in self.annotation_document.pages:
            for block in page.blocks:
                if block.group_id == group_id:
                    block.group_id = None
                    count += 1

        self._render_current_page()

        # Восстанавливаем зум и позицию
        self.page_viewer.setTransform(saved_transform)
        self.page_viewer.zoom_factor = saved_zoom_factor
        self.page_viewer.horizontalScrollBar().setValue(saved_h_scroll)
        self.page_viewer.verticalScrollBar().setValue(saved_v_scroll)

        self._update_groups_tree()
        self._auto_save_annotation()

        from apps.rd_desktop.gui.toast import show_toast

        show_toast(self, f"Группа расформирована ({count} блоков)")

    def _delete_group_blocks(self, group_id: str):
        """Удалить все блоки группы"""
        if not self.annotation_document or not group_id:
            return

        # Подсчитываем блоки
        count = sum(
            1
            for page in self.annotation_document.pages
            for block in page.blocks
            if block.group_id == group_id
        )

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить все {count} блоков группы?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        self._save_undo_state()

        # Сохраняем текущий зум и позицию
        saved_transform = self.page_viewer.transform()
        saved_zoom_factor = self.page_viewer.zoom_factor
        saved_h_scroll = self.page_viewer.horizontalScrollBar().value()
        saved_v_scroll = self.page_viewer.verticalScrollBar().value()

        for page in self.annotation_document.pages:
            page.blocks = [b for b in page.blocks if b.group_id != group_id]

        self._render_current_page()

        # Восстанавливаем зум и позицию
        self.page_viewer.setTransform(saved_transform)
        self.page_viewer.zoom_factor = saved_zoom_factor
        self.page_viewer.horizontalScrollBar().setValue(saved_h_scroll)
        self.page_viewer.verticalScrollBar().setValue(saved_v_scroll)

        self._update_groups_tree()
        self._auto_save_annotation()

        from apps.rd_desktop.gui.toast import show_toast

        show_toast(self, f"Удалено {count} блоков")

    def _remove_block_from_group(self, page_num: int, block_idx: int):
        """Убрать блок из группы"""
        if not self.annotation_document:
            return

        if page_num >= len(self.annotation_document.pages):
            return

        page = self.annotation_document.pages[page_num]
        if block_idx >= len(page.blocks):
            return

        self._save_undo_state()

        # Сохраняем текущий зум и позицию
        saved_transform = self.page_viewer.transform()
        saved_zoom_factor = self.page_viewer.zoom_factor
        saved_h_scroll = self.page_viewer.horizontalScrollBar().value()
        saved_v_scroll = self.page_viewer.verticalScrollBar().value()

        page.blocks[block_idx].group_id = None
        page.blocks[block_idx].group_name = None

        self._render_current_page()

        # Восстанавливаем зум и позицию
        self.page_viewer.setTransform(saved_transform)
        self.page_viewer.zoom_factor = saved_zoom_factor
        self.page_viewer.horizontalScrollBar().setValue(saved_h_scroll)
        self.page_viewer.verticalScrollBar().setValue(saved_v_scroll)

        self._update_groups_tree()
        self._auto_save_annotation()

        from apps.rd_desktop.gui.toast import show_toast

        show_toast(self, "Блок удалён из группы")

    def _rename_group(self, group_id: str, current_name: str):
        """Переименовать группу"""
        if not self.annotation_document or not group_id:
            return

        from PySide6.QtWidgets import QInputDialog

        new_name, ok = QInputDialog.getText(
            self, "Переименовать группу", "Новое название группы:", text=current_name
        )

        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()

        self._save_undo_state()

        # Сохраняем текущий зум и позицию
        saved_transform = self.page_viewer.transform()
        saved_zoom_factor = self.page_viewer.zoom_factor
        saved_h_scroll = self.page_viewer.horizontalScrollBar().value()
        saved_v_scroll = self.page_viewer.verticalScrollBar().value()

        # Обновляем название у всех блоков группы
        for page in self.annotation_document.pages:
            for block in page.blocks:
                if block.group_id == group_id:
                    block.group_name = new_name

        self._render_current_page()

        # Восстанавливаем зум и позицию
        self.page_viewer.setTransform(saved_transform)
        self.page_viewer.zoom_factor = saved_zoom_factor
        self.page_viewer.horizontalScrollBar().setValue(saved_h_scroll)
        self.page_viewer.verticalScrollBar().setValue(saved_v_scroll)

        self._update_groups_tree()
        self.blocks_tree_manager.update_blocks_tree()
        self._auto_save_annotation()

        from apps.rd_desktop.gui.toast import show_toast

        show_toast(self, f"Группа переименована: {new_name}")
