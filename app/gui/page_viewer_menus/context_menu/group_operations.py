"""Операции с группами из контекстного меню"""
import logging

logger = logging.getLogger(__name__)


class GroupOperationsMixin:
    """Миксин для операций группировки блоков"""

    def _group_blocks(self, blocks_data: list):
        """Сгруппировать блоки"""
        main_window = self.parent().window()
        if (
            not hasattr(main_window, "annotation_document")
            or not main_window.annotation_document
        ):
            return

        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return

        page = main_window.annotation_document.pages[current_page]

        group_id = getattr(main_window, "selected_group_id", None)
        group_name = None

        if group_id:
            for block in page.blocks:
                if block.group_id == group_id and block.group_name:
                    group_name = block.group_name
                    break
        else:
            from app.gui.group_name_dialog import GroupNameDialog

            dialog = GroupNameDialog(
                main_window,
                blocks_data,
                lambda data, gid, name: self._apply_group_from_context(data, gid, name),
            )
            dialog.show()
            return

        self._apply_group_from_context(blocks_data, group_id, group_name)

    def _apply_group_from_context(
        self, blocks_data: list, group_id: str, group_name: str
    ):
        """Применить группировку к блокам из контекстного меню"""
        main_window = self.parent().window()
        if (
            not hasattr(main_window, "annotation_document")
            or not main_window.annotation_document
        ):
            return

        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return

        page = main_window.annotation_document.pages[current_page]

        if hasattr(main_window, "_save_undo_state"):
            main_window._save_undo_state()

        saved_transform = self.transform()
        saved_zoom_factor = self.zoom_factor
        saved_h_scroll = self.horizontalScrollBar().value()
        saved_v_scroll = self.verticalScrollBar().value()

        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                page.blocks[block_idx].group_id = group_id
                page.blocks[block_idx].group_name = group_name

        main_window._render_current_page()

        self.setTransform(saved_transform)
        self.zoom_factor = saved_zoom_factor
        self.horizontalScrollBar().setValue(saved_h_scroll)
        self.verticalScrollBar().setValue(saved_v_scroll)

        if hasattr(main_window, "blocks_tree_manager"):
            main_window.blocks_tree_manager.update_blocks_tree()
        if hasattr(main_window, "_update_groups_tree"):
            main_window._update_groups_tree()
        if hasattr(main_window, "_auto_save_annotation"):
            main_window._auto_save_annotation()

        from app.gui.toast import show_toast

        show_toast(main_window, f"Блоки сгруппированы: {group_name}")

    def _add_blocks_to_group(self, blocks_data: list, group_id: str):
        """Добавить блоки в существующую группу"""
        main_window = self.parent().window()
        if (
            not hasattr(main_window, "annotation_document")
            or not main_window.annotation_document
        ):
            return

        current_page = main_window.current_page
        if current_page >= len(main_window.annotation_document.pages):
            return

        page = main_window.annotation_document.pages[current_page]

        group_name = None
        for p in main_window.annotation_document.pages:
            for block in p.blocks:
                if block.group_id == group_id and block.group_name:
                    group_name = block.group_name
                    break
            if group_name:
                break

        if hasattr(main_window, "_save_undo_state"):
            main_window._save_undo_state()

        saved_transform = self.transform()
        saved_zoom_factor = self.zoom_factor
        saved_h_scroll = self.horizontalScrollBar().value()
        saved_v_scroll = self.verticalScrollBar().value()

        for data in blocks_data:
            block_idx = data["idx"]
            if block_idx < len(page.blocks):
                page.blocks[block_idx].group_id = group_id
                page.blocks[block_idx].group_name = group_name

        main_window._render_current_page()

        self.setTransform(saved_transform)
        self.zoom_factor = saved_zoom_factor
        self.horizontalScrollBar().setValue(saved_h_scroll)
        self.verticalScrollBar().setValue(saved_v_scroll)

        if hasattr(main_window, "blocks_tree_manager"):
            main_window.blocks_tree_manager.update_blocks_tree()
        if hasattr(main_window, "_update_groups_tree"):
            main_window._update_groups_tree()
        if hasattr(main_window, "_auto_save_annotation"):
            main_window._auto_save_annotation()

        from app.gui.toast import show_toast

        show_toast(main_window, f"Блоки добавлены в группу: {group_name}")
