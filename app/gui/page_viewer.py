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
        self.current_page: int = 0
        
        # Состояние рисования
        self.drawing = False
        self.start_point: Optional[QPointF] = None
        self.rubber_band_item: Optional[QGraphicsRectItem] = None  # временный прямоугольник
        self.selected_block_idx: Optional[int] = None
        
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
    
    def set_page_image(self, pil_image: Image.Image, page_number: int = 0):
        """
        Установить изображение страницы
        
        Args:
            pil_image: изображение страницы из PIL
            page_number: номер страницы
        """
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
        
        # Сбрасываем масштаб
        self.resetTransform()
        self.zoom_factor = 1.0
        
        self._update_display()
    
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
        """Обработка движения мыши - рисование rubber band"""
        if self.drawing and self.start_point and self.rubber_band_item:
            scene_pos = self.mapToScene(event.pos())
            rect = QRectF(self.start_point, scene_pos).normalized()
            self.rubber_band_item.setRect(rect)
        else:
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
        if event.button() == Qt.LeftButton and self.drawing:
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
    
    def reset_zoom(self):
        """Сбросить масштаб к 100%"""
        self.resetTransform()
        self.zoom_factor = 1.0
    
    def fit_to_view(self):
        """Подогнать страницу под размер view"""
        if self.page_image:
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            self.zoom_factor = self.transform().m11()

