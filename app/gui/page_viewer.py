"""
Виджет просмотра страницы PDF
Отображение страницы с возможностью рисовать прямоугольники для разметки
"""

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QMenu
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QImage, QColor, QWheelEvent, QBrush, QAction
from PIL import Image
from typing import Optional, List, Dict
from app.models import Block, BlockType, BlockSource


class PageViewer(QGraphicsView):
    """
    Виджет для отображения страницы PDF и рисования блоков разметки
    Основан на QGraphicsView с поддержкой масштабирования колесом мыши
    
    Signals:
        blockDrawn: испускается при завершении рисования блока (x1, y1, x2, y2)
        block_selected: испускается при выборе существующего блока (int - индекс)
        blockEditing: испускается при двойном клике по блоку (int - индекс)
        blockDeleted: испускается при удалении блока (int - индекс)
        page_changed: испускается при запросе смены страницы (int - новая страница)
    """
    
    blockDrawn = Signal(int, int, int, int)  # x1, y1, x2, y2
    block_selected = Signal(int)
    blockEditing = Signal(int)  # индекс блока для редактирования
    blockDeleted = Signal(int)  # индекс блока, который удалили
    blockMoved = Signal(int, int, int, int, int)  # индекс, x1, y1, x2, y2
    page_changed = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Scene для графики
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # Изображение страницы
        self.page_image: Optional[QPixmap] = None
        self.image_item: Optional[QGraphicsPixmapItem] = None
        self.current_blocks: List[Block] = []
        self.block_items: Dict[str, QGraphicsRectItem] = {}  # id блока -> QGraphicsRectItem
        self.resize_handles: List[QGraphicsRectItem] = []  # хэндлы изменения размера
        self.current_page: int = 0
        
        # Состояние рисования
        self.drawing = False
        self.start_point: Optional[QPointF] = None
        self.rubber_band_item: Optional[QGraphicsRectItem] = None  # временный прямоугольник
        self.selected_block_idx: Optional[int] = None
        
        # Состояние перемещения/изменения размера
        self.moving_block = False
        self.resizing_block = False
        self.resize_handle = None  # 'tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'
        self.move_start_pos: Optional[QPointF] = None
        self.original_block_rect: Optional[QRectF] = None
        
        # Масштабирование
        self.zoom_factor = 1.0
        
        # Настройка UI
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        # Настройки view
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumSize(800, 600)
        
        # Включаем отслеживание мыши и фокус
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Для запоминания позиции контекстного меню
        self.context_menu_pos: Optional[QPointF] = None
    
    def set_page_image(self, pil_image: Image.Image, page_number: int = 0, reset_zoom: bool = True):
        """
        Установить изображение страницы
        
        Args:
            pil_image: изображение страницы из PIL (может быть None для очистки)
            page_number: номер страницы
            reset_zoom: сбрасывать ли масштаб (по умолчанию True)
        """
        # Если изображение None - очищаем сцену
        if pil_image is None:
            self.scene.clear()
            self.page_image = None
            self.image_item = None
            self.current_page = page_number
            self.selected_block_idx = None
            self.block_items.clear()
            return
        
        # Конвертация PIL в QPixmap
        img_bytes = pil_image.tobytes("raw", "RGB")
        qimage = QImage(img_bytes, pil_image.width, pil_image.height, 
                       pil_image.width * 3, QImage.Format_RGB888)
        self.page_image = QPixmap.fromImage(qimage)
        self.current_page = page_number
        
        # Очищаем сцену и добавляем изображение
        self.scene.clear()
        self.image_item = self.scene.addPixmap(self.page_image)
        self.scene.setSceneRect(QRectF(self.page_image.rect()))
        
        # Сбрасываем выбранный блок при смене страницы
        self.selected_block_idx = None
        self.block_items.clear()
        
        # Сбрасываем масштаб только если указано
        if reset_zoom:
            self.resetTransform()
            self.zoom_factor = 1.0
    
    def set_blocks(self, blocks: List[Block]):
        """
        Установить список блоков для отображения
        
        Args:
            blocks: список блоков
        """
        self.current_blocks = blocks
        self._clear_block_items()
        self._draw_all_blocks()
    
    def _clear_block_items(self):
        """Очистить все QGraphicsRectItem блоков"""
        for item in self.block_items.values():
            self.scene.removeItem(item)
        self.block_items.clear()
        self._clear_resize_handles()
    
    def _clear_resize_handles(self):
        """Очистить все хэндлы изменения размера"""
        for handle in self.resize_handles:
            try:
                if handle.scene() is not None:
                    self.scene.removeItem(handle)
            except RuntimeError:
                pass
        self.resize_handles.clear()
    
    def _draw_all_blocks(self):
        """Отрисовать все блоки как QGraphicsRectItem"""
        for idx, block in enumerate(self.current_blocks):
            self._draw_block(block, idx)
    
    def _draw_block(self, block: Block, idx: int):
        """
        Отрисовать один блок как QGraphicsRectItem
        
        Args:
            block: блок для отрисовки
            idx: индекс блока в списке
        """
        x1, y1, x2, y2 = block.coords_px
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        
        # Создаём QGraphicsRectItem
        color = self._get_block_color(block.block_type)
        pen = QPen(color, 2)
        
        # Авто-блоки отображаем пунктирной линией
        if block.source == BlockSource.AUTO:
            pen.setStyle(Qt.DashLine)
            pen.setWidth(3)
        
        # Выделяем выбранный блок
        if idx == self.selected_block_idx:
            pen.setWidth(4)
        
        # Полупрозрачная заливка
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), 30))
        
        rect_item = QGraphicsRectItem(rect)
        rect_item.setPen(pen)
        rect_item.setBrush(brush)
        
        # Сохраняем ссылку на блок в userData
        rect_item.setData(0, block.id)
        rect_item.setData(1, idx)
        
        self.scene.addItem(rect_item)
        self.block_items[block.id] = rect_item
        
        # Рисуем хэндлы для выделенного блока
        if idx == self.selected_block_idx:
            self._draw_resize_handles(rect)
    
    def _get_block_color(self, block_type: BlockType) -> QColor:
        """Получить цвет для типа блока"""
        colors = {
            BlockType.TEXT: QColor(0, 255, 0),      # зелёный
            BlockType.TABLE: QColor(0, 0, 255),     # синий
            BlockType.IMAGE: QColor(255, 165, 0)    # оранжевый
        }
        return colors.get(block_type, QColor(128, 128, 128))
    
    def wheelEvent(self, event: QWheelEvent):
        """Обработка колеса мыши для масштабирования"""
        # Определяем направление прокрутки
        delta = event.angleDelta().y()
        
        if delta > 0:
            # Увеличение
            factor = 1.15
        else:
            # Уменьшение
            factor = 1 / 1.15
        
        # Применяем масштабирование
        self.zoom_factor *= factor
        self.scale(factor, factor)
    
    def mousePressEvent(self, event):
        """Обработка нажатия мыши"""
        if event.button() == Qt.LeftButton:
            # Преобразуем координаты в координаты сцены
            scene_pos = self.mapToScene(event.pos())
            
            # Проверяем, попали ли в существующий блок
            clicked_block = self._find_block_at_position(scene_pos)
            
            if clicked_block is not None:
                self.selected_block_idx = clicked_block
                self.block_selected.emit(clicked_block)
                
                # Определяем, куда кликнули: на хэндл изменения размера или в центр
                block = self.current_blocks[clicked_block]
                x1, y1, x2, y2 = block.coords_px
                block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                
                resize_handle = self._get_resize_handle(scene_pos, block_rect)
                
                if resize_handle:
                    # Начинаем изменение размера
                    self.resizing_block = True
                    self.resize_handle = resize_handle
                    self.move_start_pos = scene_pos
                    self.original_block_rect = block_rect
                else:
                    # Начинаем перемещение
                    self.moving_block = True
                    self.move_start_pos = scene_pos
                    self.original_block_rect = block_rect
                
                self._redraw_blocks()  # перерисовываем для выделения
            else:
                # Начинаем рисовать новый блок (rubber band)
                self.drawing = True
                self.start_point = scene_pos
                
                # Создаём временный rubber band rect
                self.rubber_band_item = QGraphicsRectItem(QRectF(scene_pos, scene_pos))
                pen = QPen(QColor(255, 0, 0), 2, Qt.DashLine)
                brush = QBrush(QColor(255, 0, 0, 30))
                self.rubber_band_item.setPen(pen)
                self.rubber_band_item.setBrush(brush)
                self.scene.addItem(self.rubber_band_item)
        
        elif event.button() == Qt.RightButton:
            # Сохраняем позицию для контекстного меню
            scene_pos = self.mapToScene(event.pos())
            self.context_menu_pos = scene_pos
            
            # Проверяем, попали ли в существующий блок
            clicked_block = self._find_block_at_position(scene_pos)
            if clicked_block is not None:
                self.selected_block_idx = clicked_block
                self.block_selected.emit(clicked_block)
                self._redraw_blocks()
        
        elif event.button() == Qt.MiddleButton:
            # Средняя кнопка мыши для перетаскивания
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Обработка движения мыши - рисование rubber band, перемещение или изменение размера"""
        scene_pos = self.mapToScene(event.pos())
        
        if self.drawing and self.start_point and self.rubber_band_item:
            # Рисование нового блока
            rect = QRectF(self.start_point, scene_pos).normalized()
            self.rubber_band_item.setRect(rect)
        
        elif self.moving_block and self.selected_block_idx is not None:
            # Перемещение блока
            delta = scene_pos - self.move_start_pos
            new_rect = self.original_block_rect.translated(delta)
            self._update_block_rect(self.selected_block_idx, new_rect)
        
        elif self.resizing_block and self.selected_block_idx is not None:
            # Изменение размера блока
            new_rect = self._calculate_resized_rect(scene_pos)
            self._update_block_rect(self.selected_block_idx, new_rect)
        
        else:
            # Обновляем курсор при наведении на хэндлы
            if self.selected_block_idx is not None and 0 <= self.selected_block_idx < len(self.current_blocks):
                block = self.current_blocks[self.selected_block_idx]
                x1, y1, x2, y2 = block.coords_px
                block_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                resize_handle = self._get_resize_handle(scene_pos, block_rect)
                self._set_cursor_for_handle(resize_handle)
            else:
                self.setCursor(Qt.ArrowCursor)
            
            super().mouseMoveEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Обработка двойного клика - редактирование блока"""
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            clicked_block = self._find_block_at_position(scene_pos)
            
            if clicked_block is not None:
                self.blockEditing.emit(clicked_block)
    
    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши - финализация прямоугольника"""
        if event.button() == Qt.LeftButton:
            if self.drawing:
                self.drawing = False
                
                if self.rubber_band_item:
                    rect = self.rubber_band_item.rect()
                    
                    # Удаляем rubber band
                    self.scene.removeItem(self.rubber_band_item)
                    self.rubber_band_item = None
                    
                    # Проверяем минимальный размер
                    if rect.width() > 10 and rect.height() > 10:
                        # Посылаем сигнал с координатами
                        x1 = int(rect.x())
                        y1 = int(rect.y())
                        x2 = int(rect.x() + rect.width())
                        y2 = int(rect.y() + rect.height())
                        
                        self.blockDrawn.emit(x1, y1, x2, y2)
                
                self.start_point = None
            
            elif self.moving_block or self.resizing_block:
                # Завершение перемещения или изменения размера
                if self.selected_block_idx is not None and 0 <= self.selected_block_idx < len(self.current_blocks):
                    block = self.current_blocks[self.selected_block_idx]
                    x1, y1, x2, y2 = block.coords_px
                    self.blockMoved.emit(self.selected_block_idx, x1, y1, x2, y2)
                
                self.moving_block = False
                self.resizing_block = False
                self.resize_handle = None
                self.move_start_pos = None
                self.original_block_rect = None
        
        elif event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.NoDrag)
            super().mouseReleaseEvent(event)
        
        elif event.button() == Qt.RightButton:
            # Показываем контекстное меню
            if self.selected_block_idx is not None:
                self._show_context_menu(event.globalPos())
    
    def keyPressEvent(self, event):
        """Обработка нажатия клавиши Delete"""
        if event.key() == Qt.Key_Delete:
            if self.selected_block_idx is not None:
                self.blockDeleted.emit(self.selected_block_idx)
                self.selected_block_idx = None
        else:
            super().keyPressEvent(event)
    
    def contextMenuEvent(self, event):
        """Обработка контекстного меню"""
        if self.selected_block_idx is not None:
            self._show_context_menu(event.globalPos())
    
    def _show_context_menu(self, global_pos):
        """Показать контекстное меню"""
        menu = QMenu(self)
        
        edit_action = menu.addAction("✏️ Редактировать")
        edit_action.triggered.connect(lambda: self.blockEditing.emit(self.selected_block_idx))
        
        delete_action = menu.addAction("🗑️ Удалить блок")
        delete_action.triggered.connect(lambda: self.blockDeleted.emit(self.selected_block_idx))
        
        menu.exec(global_pos)
    
    def _find_block_at_position(self, scene_pos: QPointF) -> Optional[int]:
        """
        Найти блок в заданной позиции
        
        Returns:
            Индекс блока или None
        """
        # Используем itemAt для проверки QGraphicsRectItem
        item = self.scene.itemAt(scene_pos, self.transform())
        
        if isinstance(item, QGraphicsRectItem) and item != self.rubber_band_item:
            # Получаем индекс из userData
            idx = item.data(1)
            if idx is not None:
                return idx
        
        return None
    
    def _redraw_blocks(self):
        """Перерисовать все блоки (например, после смены выделения)"""
        self._clear_block_items()
        self._draw_all_blocks()
    
    def _get_resize_handle(self, pos: QPointF, rect: QRectF) -> Optional[str]:
        """
        Определить, попал ли клик на хэндл изменения размера
        
        Returns:
            'tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r' или None
        """
        handle_size = 10 / self.zoom_factor  # размер хэндла с учетом масштаба
        
        x, y = pos.x(), pos.y()
        left, top = rect.left(), rect.top()
        right, bottom = rect.right(), rect.bottom()
        
        # Проверяем углы (приоритет над сторонами)
        if abs(x - left) <= handle_size and abs(y - top) <= handle_size:
            return 'tl'  # top-left
        if abs(x - right) <= handle_size and abs(y - top) <= handle_size:
            return 'tr'  # top-right
        if abs(x - left) <= handle_size and abs(y - bottom) <= handle_size:
            return 'bl'  # bottom-left
        if abs(x - right) <= handle_size and abs(y - bottom) <= handle_size:
            return 'br'  # bottom-right
        
        # Проверяем стороны
        if abs(y - top) <= handle_size and left <= x <= right:
            return 't'  # top
        if abs(y - bottom) <= handle_size and left <= x <= right:
            return 'b'  # bottom
        if abs(x - left) <= handle_size and top <= y <= bottom:
            return 'l'  # left
        if abs(x - right) <= handle_size and top <= y <= bottom:
            return 'r'  # right
        
        return None
    
    def _set_cursor_for_handle(self, handle: Optional[str]):
        """Установить курсор в зависимости от хэндла"""
        if handle in ['tl', 'br']:
            self.setCursor(Qt.SizeFDiagCursor)
        elif handle in ['tr', 'bl']:
            self.setCursor(Qt.SizeBDiagCursor)
        elif handle in ['t', 'b']:
            self.setCursor(Qt.SizeVerCursor)
        elif handle in ['l', 'r']:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
    
    def _calculate_resized_rect(self, current_pos: QPointF) -> QRectF:
        """Вычислить новый прямоугольник при изменении размера"""
        if not self.original_block_rect or not self.move_start_pos:
            return self.original_block_rect
        
        delta = current_pos - self.move_start_pos
        rect = QRectF(self.original_block_rect)
        
        handle = self.resize_handle
        
        # Изменяем соответствующие стороны
        if 'l' in handle:
            rect.setLeft(rect.left() + delta.x())
        if 'r' in handle:
            rect.setRight(rect.right() + delta.x())
        if 't' in handle:
            rect.setTop(rect.top() + delta.y())
        if 'b' in handle:
            rect.setBottom(rect.bottom() + delta.y())
        
        # Минимальный размер
        if rect.width() < 10:
            if 'l' in handle:
                rect.setLeft(rect.right() - 10)
            else:
                rect.setRight(rect.left() + 10)
        
        if rect.height() < 10:
            if 't' in handle:
                rect.setTop(rect.bottom() - 10)
            else:
                rect.setBottom(rect.top() + 10)
        
        return rect.normalized()
    
    def _update_block_rect(self, block_idx: int, new_rect: QRectF):
        """Обновить координаты блока"""
        if block_idx >= len(self.current_blocks):
            return
        
        block = self.current_blocks[block_idx]
        new_coords = (
            int(new_rect.x()),
            int(new_rect.y()),
            int(new_rect.x() + new_rect.width()),
            int(new_rect.y() + new_rect.height())
        )
        
        # Обновляем координаты в блоке (временно, без пересчета нормализованных)
        block.coords_px = new_coords
        
        # Перерисовываем блок
        self._redraw_blocks()
    
    def reset_zoom(self):
        """Сбросить масштаб к 100%"""
        self.resetTransform()
        self.zoom_factor = 1.0
    
    def fit_to_view(self):
        """Подогнать страницу под размер view"""
        if self.page_image:
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            self.zoom_factor = self.transform().m11()
    
    def _draw_resize_handles(self, rect: QRectF):
        """Нарисовать хэндлы изменения размера на углах и сторонах прямоугольника"""
        handle_size = 8 / self.zoom_factor
        handle_color = QColor(255, 0, 0)
        
        positions = [
            (rect.left(), rect.top()),          # top-left
            (rect.right(), rect.top()),         # top-right
            (rect.left(), rect.bottom()),       # bottom-left
            (rect.right(), rect.bottom()),      # bottom-right
            (rect.center().x(), rect.top()),    # top-center
            (rect.center().x(), rect.bottom()), # bottom-center
            (rect.left(), rect.center().y()),   # left-center
            (rect.right(), rect.center().y()),  # right-center
        ]
        
        for x, y in positions:
            handle_rect = QRectF(x - handle_size/2, y - handle_size/2, 
                               handle_size, handle_size)
            handle = QGraphicsRectItem(handle_rect)
            handle.setPen(QPen(handle_color, 1))
            handle.setBrush(QBrush(QColor(255, 255, 255)))
            self.scene.addItem(handle)
            self.resize_handles.append(handle)

