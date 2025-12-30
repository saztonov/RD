"""
Миксин для обработки блоков и событий
"""

import logging
import uuid
from PySide6.QtWidgets import QTreeWidgetItem, QMessageBox, QMenu
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QKeyEvent
from rd_core.models import Block, BlockType, BlockSource, ShapeType, Page

logger = logging.getLogger(__name__)


class BlockHandlersMixin:
    """Миксин для обработки блоков"""
    
    _categories_cache = None
    
    def _get_category_name(self, category_id: str) -> str:
        """Получить название категории по ID"""
        if not category_id:
            return ""
        
        if BlockHandlersMixin._categories_cache is None:
            try:
                from app.tree_client import TreeClient
                client = TreeClient()
                if client.is_available():
                    BlockHandlersMixin._categories_cache = {
                        cat["id"]: cat["name"] for cat in client.get_image_categories()
                    }
                else:
                    BlockHandlersMixin._categories_cache = {}
            except Exception:
                BlockHandlersMixin._categories_cache = {}
        
        return BlockHandlersMixin._categories_cache.get(category_id, "")
    
    def _get_or_create_page(self, page_num: int) -> Page:
        """Получить страницу или создать новую"""
        if not self.annotation_document:
            return None
        
        while len(self.annotation_document.pages) <= page_num:
            new_page_num = len(self.annotation_document.pages)
            
            # Приоритет: реальное изображение > get_page_dimensions > fallback
            if new_page_num in self.page_images:
                img = self.page_images[new_page_num]
                page = Page(page_number=new_page_num, width=img.width, height=img.height)
            elif self.pdf_document:
                dims = self.pdf_document.get_page_dimensions(new_page_num)
                if dims:
                    page = Page(page_number=new_page_num, width=dims[0], height=dims[1])
                else:
                    page = Page(page_number=new_page_num, width=595, height=842)
            else:
                page = Page(page_number=new_page_num, width=595, height=842)
            
            self.annotation_document.pages.append(page)
        
        return self.annotation_document.pages[page_num]
    
    def _on_block_drawn(self, x1: int, y1: int, x2: int, y2: int):
        """Обработка завершения рисования блока (прямоугольник)"""
        if not self.annotation_document:
            return
        
        self._save_undo_state()
        
        checked_action = self.block_type_group.checkedAction()
        action_data = checked_action.data() if checked_action else {}
        block_type = action_data.get("block_type", BlockType.TEXT) if isinstance(action_data, dict) else BlockType.TEXT
        category_code = action_data.get("category_code") if isinstance(action_data, dict) else None
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        block = Block.create(
            page_index=self.current_page,
            coords_px=(x1, y1, x2, y2),
            page_width=current_page_data.width,
            page_height=current_page_data.height,
            block_type=block_type,
            source=BlockSource.USER,
            shape_type=ShapeType.RECTANGLE
        )
        if category_code:
            block.category_code = category_code
        
        logger.debug(f"Block created: {block.id} coords_px={block.coords_px} page_size={current_page_data.width}x{current_page_data.height}")
        
        current_page_data.blocks.append(block)
        new_block_idx = len(current_page_data.blocks) - 1
        
        # Автоматически выбираем созданный блок для возможности изменения размера
        self.page_viewer.selected_block_idx = new_block_idx
        self.page_viewer.set_blocks(current_page_data.blocks)
        
        # Отложенное обновление дерева (не блокирует UI)
        QTimer.singleShot(0, self.blocks_tree_manager.update_blocks_tree)
        self._auto_save_annotation()
    
    def _on_polygon_drawn(self, points: list):
        """Обработка завершения рисования полигона"""
        if not self.annotation_document or not points or len(points) < 3:
            return
        
        self._save_undo_state()
        
        checked_action = self.block_type_group.checkedAction()
        action_data = checked_action.data() if checked_action else {}
        block_type = action_data.get("block_type", BlockType.TEXT) if isinstance(action_data, dict) else BlockType.TEXT
        category_code = action_data.get("category_code") if isinstance(action_data, dict) else None
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        # Вычисляем bounding box для coords_px
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        
        block = Block.create(
            page_index=self.current_page,
            coords_px=(x1, y1, x2, y2),
            page_width=current_page_data.width,
            page_height=current_page_data.height,
            block_type=block_type,
            source=BlockSource.USER,
            shape_type=ShapeType.POLYGON,
            polygon_points=points
        )
        if category_code:
            block.category_code = category_code
        
        logger.debug(f"Polygon created: {block.id} bbox={block.coords_px} vertices={len(points)}")
        
        current_page_data.blocks.append(block)
        new_block_idx = len(current_page_data.blocks) - 1
        
        # Автоматически выбираем созданный блок
        self.page_viewer.selected_block_idx = new_block_idx
        self.page_viewer.set_blocks(current_page_data.blocks)
        
        # Отложенное обновление дерева (не блокирует UI)
        QTimer.singleShot(0, self.blocks_tree_manager.update_blocks_tree)
        self._auto_save_annotation()
    
    def _on_block_selected(self, block_idx: int):
        """Обработка выбора блока"""
        if not self.annotation_document:
            self._hide_hint_panel()
            self._hide_ocr_preview()
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data or not (0 <= block_idx < len(current_page_data.blocks)):
            self._hide_hint_panel()
            self._hide_ocr_preview()
            return
        
        block = current_page_data.blocks[block_idx]
        
        # Показываем панель подсказки для IMAGE блоков
        if block.block_type == BlockType.IMAGE:
            self._show_hint_panel(block)
        else:
            self._hide_hint_panel()
        
        # Показываем OCR preview для выбранного блока
        self._show_ocr_preview(block.id)
        
        self.blocks_tree_manager.select_block_in_tree(block_idx)
    
    def _show_hint_panel(self, block):
        """Активировать панель подсказки для блока"""
        if hasattr(self, 'hint_group'):
            self._selected_image_block = block
            self.hint_edit.blockSignals(True)
            self.hint_edit.setPlainText(block.hint or "")
            self.hint_edit.blockSignals(False)
            self.hint_group.setEnabled(True)
    
    def _hide_hint_panel(self):
        """Деактивировать панель подсказки"""
        if hasattr(self, 'hint_group'):
            self._selected_image_block = None
            self.hint_edit.blockSignals(True)
            self.hint_edit.clear()
            self.hint_edit.blockSignals(False)
            self.hint_group.setEnabled(False)
    
    def _show_ocr_preview(self, block_id: str):
        """Показать OCR preview для блока"""
        if hasattr(self, 'ocr_preview') and self.ocr_preview:
            self.ocr_preview.show_block(block_id)
    
    def _hide_ocr_preview(self):
        """Скрыть OCR preview"""
        if hasattr(self, 'ocr_preview') and self.ocr_preview:
            self.ocr_preview.clear()
    
    def _load_ocr_result_file(self):
        """Загрузить _result.json для текущего PDF"""
        if hasattr(self, 'ocr_preview') and self.ocr_preview:
            pdf_path = getattr(self, '_current_pdf_path', None)
            r2_key = getattr(self, '_current_r2_key', None)
            if pdf_path:
                self.ocr_preview.load_result_file(pdf_path, r2_key)
    
    def _on_blocks_selected(self, block_indices: list):
        """Обработка множественного выбора блоков"""
        self._hide_hint_panel()
        if not self.annotation_document or not block_indices:
            return
        
        self.blocks_tree_manager.select_blocks_in_tree(block_indices)
    
    def _on_block_editing(self, block_idx: int):
        """Обработка двойного клика для редактирования блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            self.page_viewer.selected_block_idx = block_idx
            self._on_block_selected(block_idx)
    
    def _on_block_deleted(self, block_idx: int):
        """Обработка удаления блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            self._save_undo_state()
            
            self.page_viewer.selected_block_idx = None
            del current_page_data.blocks[block_idx]
            
            self.page_viewer.set_blocks(current_page_data.blocks)
            self.blocks_tree_manager.update_blocks_tree()
            
            # Авто-сохранение разметки
            self._auto_save_annotation()
    
    def _on_blocks_deleted(self, block_indices: list):
        """Обработка удаления множественных блоков"""
        if not self.annotation_document or not block_indices:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        self._save_undo_state()
        
        # Сортируем индексы в обратном порядке для корректного удаления
        sorted_indices = sorted(block_indices, reverse=True)
        
        for block_idx in sorted_indices:
            if 0 <= block_idx < len(current_page_data.blocks):
                del current_page_data.blocks[block_idx]
        
        # Очищаем выделение
        self.page_viewer.selected_block_idx = None
        self.page_viewer.selected_block_indices = []
        
        self.page_viewer.set_blocks(current_page_data.blocks)
        self.blocks_tree_manager.update_blocks_tree()
        
        # Авто-сохранение разметки
        self._auto_save_annotation()
    
    def _on_block_moved(self, block_idx: int, x1: int, y1: int, x2: int, y2: int):
        """Обработка перемещения/изменения размера блока"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        if 0 <= block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[block_idx]
            block.update_coords_px((x1, y1, x2, y2),
                                   current_page_data.width,
                                   current_page_data.height)
            
            # Авто-сохранение разметки
            self._auto_save_annotation()
    
    def _on_tree_block_clicked(self, item: QTreeWidgetItem, column: int):
        """Клик по блоку в дереве"""
        # Определяем, какое дерево было кликнуто
        tree = self.sender()
        if tree is None:
            tree = self.blocks_tree
        
        # Получаем все выбранные элементы
        selected_items = tree.selectedItems()
        
        # Фильтруем только блоки
        selected_blocks = []
        for sel_item in selected_items:
            sel_data = sel_item.data(0, Qt.UserRole)
            if sel_data and isinstance(sel_data, dict) and sel_data.get("type") == "block":
                selected_blocks.append(sel_data)
        
        if not selected_blocks:
            return
        
        # Если выбрано несколько блоков на одной странице
        if len(selected_blocks) > 1:
            # Проверяем, что все блоки на одной странице
            page_num = selected_blocks[0]["page"]
            if all(b["page"] == page_num for b in selected_blocks):
                # Переключаем страницу если нужно
                if self.current_page != page_num:
                    self.navigation_manager.save_current_zoom()
                    self.current_page = page_num
                    self.navigation_manager.load_page_image(self.current_page)
                    self.navigation_manager.restore_zoom()
                
                current_page_data = self._get_or_create_page(self.current_page)
                self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
                self.page_viewer.fit_to_view()
                
                # Выделяем все блоки
                block_indices = [b["idx"] for b in selected_blocks]
                self.page_viewer.selected_block_indices = block_indices
                self.page_viewer.selected_block_idx = None
                self.page_viewer._redraw_blocks()
                
                self._hide_hint_panel()
                self._update_ui()
                return
        
        # Одиночное выделение
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict) or data.get("type") != "block":
            return
        
        page_num = data["page"]
        block_idx = data["idx"]
        
        if self.current_page != page_num:
            self.navigation_manager.save_current_zoom()
        
        self.current_page = page_num
        self.navigation_manager.load_page_image(self.current_page)
        self.navigation_manager.restore_zoom()
        
        current_page_data = self._get_or_create_page(self.current_page)
        self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
        self.page_viewer.fit_to_view()
        
        self.page_viewer.selected_block_idx = block_idx
        self.page_viewer.selected_block_indices = []
        self.page_viewer._redraw_blocks()
        
        self._update_ui()
        
        # Показ/скрытие панели подсказки для IMAGE
        current_page_data = self._get_or_create_page(self.current_page)
        if current_page_data and 0 <= block_idx < len(current_page_data.blocks):
            block = current_page_data.blocks[block_idx]
            if block.block_type == BlockType.IMAGE:
                self._show_hint_panel(block)
            else:
                self._hide_hint_panel()
            
            # Показываем OCR preview
            self._show_ocr_preview(block.id)
    
    
    def _clear_current_page(self):
        """Очистить все блоки с текущей страницы"""
        if not self.annotation_document:
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data or not current_page_data.blocks:
            QMessageBox.information(self, "Информация", "На странице нет блоков")
            return
        
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить все {len(current_page_data.blocks)} блоков со страницы {self.current_page + 1}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._save_undo_state()
            current_page_data.blocks.clear()
            self.page_viewer.set_blocks([])
            self.blocks_tree_manager.update_blocks_tree()
            self._auto_save_annotation()
            from app.gui.toast import show_toast
            show_toast(self, "Разметка страницы очищена")
    
    def _move_block_up(self):
        """Переместить выбранный блок вверх"""
        tree = self.blocks_tabs.currentWidget()
        if tree is None:
            return
        
        current_item = tree.currentItem()
        if not current_item:
            return
        
        data = current_item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict) or data.get("type") != "block":
            return
        
        page_num = data["page"]
        block_idx = data["idx"]
        
        if not self.annotation_document or page_num >= len(self.annotation_document.pages):
            return
        
        page = self.annotation_document.pages[page_num]
        
        # Проверяем, можем ли перемещать вверх
        if block_idx <= 0:
            return
        
        self._save_undo_state()
        
        # Меняем местами блоки
        page.blocks[block_idx], page.blocks[block_idx - 1] = page.blocks[block_idx - 1], page.blocks[block_idx]
        
        # Обновляем viewer и tree
        self.page_viewer.set_blocks(page.blocks)
        self.blocks_tree_manager.update_blocks_tree()
        
        # Выбираем новую позицию блока
        self.blocks_tree_manager.select_block_in_tree(block_idx - 1)
        self.page_viewer.selected_block_idx = block_idx - 1
        self.page_viewer._redraw_blocks()
        
        self._auto_save_annotation()
    
    def _move_block_down(self):
        """Переместить выбранный блок вниз"""
        tree = self.blocks_tabs.currentWidget()
        if tree is None:
            return
        
        current_item = tree.currentItem()
        if not current_item:
            return
        
        data = current_item.data(0, Qt.UserRole)
        if not data or not isinstance(data, dict) or data.get("type") != "block":
            return
        
        page_num = data["page"]
        block_idx = data["idx"]
        
        if not self.annotation_document or page_num >= len(self.annotation_document.pages):
            return
        
        page = self.annotation_document.pages[page_num]
        
        # Проверяем, можем ли перемещать вниз
        if block_idx >= len(page.blocks) - 1:
            return
        
        self._save_undo_state()
        
        # Меняем местами блоки
        page.blocks[block_idx], page.blocks[block_idx + 1] = page.blocks[block_idx + 1], page.blocks[block_idx]
        
        # Обновляем viewer и tree
        self.page_viewer.set_blocks(page.blocks)
        self.blocks_tree_manager.update_blocks_tree()
        
        # Выбираем новую позицию блока
        self.blocks_tree_manager.select_block_in_tree(block_idx + 1)
        self.page_viewer.selected_block_idx = block_idx + 1
        self.page_viewer._redraw_blocks()
        
        self._auto_save_annotation()
    
    def keyPressEvent(self, event):
        """Обработка нажатия клавиш"""
        # Ctrl+Z для отмены
        if event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            self._undo()
            return
        # Ctrl+Y для повтора
        elif event.key() == Qt.Key_Y and event.modifiers() & Qt.ControlModifier:
            self._redo()
            return
        # Ctrl+G для группировки
        elif event.key() == Qt.Key_G and event.modifiers() & Qt.ControlModifier:
            self._group_selected_blocks()
            return
        elif event.key() == Qt.Key_Left:
            self._prev_page()
            return
        elif event.key() == Qt.Key_Right:
            self._next_page()
            return
        super().keyPressEvent(event)
    
    def eventFilter(self, obj, event):
        """Обработка событий для деревьев блоков"""
        if hasattr(self, 'blocks_tree') and obj is self.blocks_tree:
            if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key_Delete:
                    current_item = obj.currentItem()
                    if current_item:
                        data = current_item.data(0, Qt.UserRole)
                        if data and isinstance(data, dict) and data.get("type") == "block":
                            page_num = data["page"]
                            block_idx = data["idx"]
                            
                            self.current_page = page_num
                            self.navigation_manager.load_page_image(self.current_page)
                            
                            current_page_data = self._get_or_create_page(self.current_page)
                            self.page_viewer.set_blocks(
                                current_page_data.blocks if current_page_data else [])
                            
                            self._on_block_deleted(block_idx)
                            self._update_ui()
                            return True
        
        return super().eventFilter(obj, event)
    
    # === Группировка блоков ===
    
    def _update_groups_tree(self):
        """Обновить дерево групп"""
        if not hasattr(self, 'groups_tree'):
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
        groups = {}  # group_id -> {"name": str, "blocks": list of (page_num, block_idx, block)}
        ungrouped_count = 0
        
        for page in self.annotation_document.pages:
            for idx, block in enumerate(page.blocks):
                if block.group_id:
                    if block.group_id not in groups:
                        groups[block.group_id] = {"name": block.group_name or "Без названия", "blocks": []}
                    groups[block.group_id]["blocks"].append((page.page_number, idx, block))
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
            group_item.setData(0, Qt.UserRole, {"type": "group", "group_id": group_id, "group_name": group_name})
            group_item.setToolTip(0, f"Блоков: {len(blocks)}")
            
            # Добавляем блоки как дочерние элементы
            for page_num, block_idx, block in blocks:
                block_item = QTreeWidgetItem(group_item)
                block_item.setText(0, f"Стр.{page_num + 1} Блок {block_idx + 1}")
                block_item.setText(1, block.block_type.value)
                # Колонка Категория (для IMAGE блоков)
                from rd_core.models import BlockType
                cat_name = self._get_category_name(block.category_id) if block.block_type == BlockType.IMAGE else ""
                block_item.setText(2, cat_name)
                block_item.setData(0, Qt.UserRole, {
                    "type": "block", 
                    "page": page_num, 
                    "idx": block_idx,
                    "group_id": group_id
                })
            
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
                    self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
                    self.page_viewer.fit_to_view()
                    
                    # Выделяем все блоки группы на этой странице
                    group_indices = [
                        idx for idx, block in enumerate(current_page_data.blocks)
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
            self.page_viewer.set_blocks(current_page_data.blocks if current_page_data else [])
            self.page_viewer.fit_to_view()
            
            self.page_viewer.selected_block_idx = block_idx
            self.page_viewer.selected_block_indices = []
            self.page_viewer._redraw_blocks()
            
            self._update_ui()
    
    def _on_groups_tree_context_menu(self, position):
        """Контекстное меню для дерева групп"""
        if not hasattr(self, 'groups_tree'):
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
                rename_action.triggered.connect(lambda: self._rename_group(group_id, data.get("group_name", "")))
                
                menu.addSeparator()
                
                # Удалить группу (разгруппировать)
                ungroup_action = menu.addAction("📤 Разгруппировать")
                ungroup_action.triggered.connect(lambda: self._ungroup_blocks(group_id))
                
                menu.addSeparator()
                
                # Удалить все блоки группы
                delete_action = menu.addAction("🗑️ Удалить все блоки группы")
                delete_action.triggered.connect(lambda: self._delete_group_blocks(group_id))
        
        elif data.get("type") == "block":
            # Удалить блок из группы
            remove_action = menu.addAction("📤 Убрать из группы")
            remove_action.triggered.connect(
                lambda: self._remove_block_from_group(data["page"], data["idx"]))
        
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
                from app.gui.toast import show_toast
                show_toast(self, "Выберите несколько блоков (Ctrl+клик)")
            return
        
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        # Проверяем, есть ли выбранная группа
        group_id = getattr(self, 'selected_group_id', None)
        group_name = None
        
        if group_id:
            # Берём название существующей группы
            for block in current_page_data.blocks:
                if block.group_id == group_id and block.group_name:
                    group_name = block.group_name
                    break
        else:
            # Показываем немодальный диалог
            from app.gui.group_name_dialog import GroupNameDialog
            dialog = GroupNameDialog(
                self, list(selected_indices),
                lambda data, gid, name: self._apply_group_to_blocks(data, gid, name)
            )
            dialog.show()
            return
        
        self._apply_group_to_blocks(list(selected_indices), group_id, group_name)
    
    def _apply_group_to_blocks(self, selected_indices: list, group_id: str, group_name: str):
        """Применить группировку к блокам на текущей странице"""
        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            return
        
        self._save_undo_state()
        
        # Применяем group_id и group_name ко всем выбранным блокам
        for block_idx in selected_indices:
            if 0 <= block_idx < len(current_page_data.blocks):
                current_page_data.blocks[block_idx].group_id = group_id
                current_page_data.blocks[block_idx].group_name = group_name
        
        # Обновляем UI
        self._render_current_page()
        self._update_groups_tree()
        self._auto_save_annotation()
        
        # Уведомление
        from app.gui.toast import show_toast
        show_toast(self, f"Блоки сгруппированы: {group_name}")
    
    def _ungroup_blocks(self, group_id: str):
        """Разгруппировать блоки (убрать группу)"""
        if not self.annotation_document or not group_id:
            return
        
        self._save_undo_state()
        
        count = 0
        for page in self.annotation_document.pages:
            for block in page.blocks:
                if block.group_id == group_id:
                    block.group_id = None
                    count += 1
        
        self._render_current_page()
        self._update_groups_tree()
        self._auto_save_annotation()
        
        from app.gui.toast import show_toast
        show_toast(self, f"Группа расформирована ({count} блоков)")
    
    def _delete_group_blocks(self, group_id: str):
        """Удалить все блоки группы"""
        if not self.annotation_document or not group_id:
            return
        
        # Подсчитываем блоки
        count = sum(1 for page in self.annotation_document.pages 
                    for block in page.blocks if block.group_id == group_id)
        
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить все {count} блоков группы?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self._save_undo_state()
        
        for page in self.annotation_document.pages:
            page.blocks = [b for b in page.blocks if b.group_id != group_id]
        
        self._render_current_page()
        self._update_groups_tree()
        self._auto_save_annotation()
        
        from app.gui.toast import show_toast
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
        
        page.blocks[block_idx].group_id = None
        page.blocks[block_idx].group_name = None
        
        self._render_current_page()
        self._update_groups_tree()
        self._auto_save_annotation()
        
        from app.gui.toast import show_toast
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
        
        # Обновляем название у всех блоков группы
        for page in self.annotation_document.pages:
            for block in page.blocks:
                if block.group_id == group_id:
                    block.group_name = new_name
        
        self._render_current_page()
        self._update_groups_tree()
        self.blocks_tree_manager.update_blocks_tree()
        self._auto_save_annotation()
        
        from app.gui.toast import show_toast
        show_toast(self, f"Группа переименована: {new_name}")

