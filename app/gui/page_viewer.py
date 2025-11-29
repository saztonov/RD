"""
Виджет просмотра страницы PDF
Отображение страницы с возможностью рисовать прямоугольники для разметки
"""

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QImage, QColor
from PIL import Image
from typing import Optional, List
from app.models import Block, BlockType


class PageViewer(QWidget):
    """
    Виджет для отображения страницы PDF и рисования блоков разметки
    
    Signals:
        block_created: испускается при создании нового блока (Block)
        block_selected: испускается при выборе существующего блока (int - индекс)
    """
    
    block_created = Signal(Block)
    block_selected = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Изображение страницы
        self.page_image: Optional[QPixmap] = None
        self.current_blocks: List[Block] = []
        
        # Состояние рисования
        self.drawing = False
        self.start_point: Optional[QPoint] = None
        self.current_rect: Optional[QRect] = None
        self.selected_block_idx: Optional[int] = None
        
        # Настройка UI
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        
        # Label для отображения изображения
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(800, 600)
        
        layout.addWidget(self.image_label)
        
        # Включаем отслеживание мыши
        self.setMouseTracking(True)
        self.image_label.setMouseTracking(True)
    
    def set_page_image(self, pil_image: Image.Image):
        """
        Установить изображение страницы
        
        Args:
            pil_image: изображение страницы из PIL
        """
        # Конвертация PIL в QPixmap
        img_bytes = pil_image.tobytes("raw", "RGB")
        qimage = QImage(img_bytes, pil_image.width, pil_image.height, 
                       pil_image.width * 3, QImage.Format_RGB888)
        self.page_image = QPixmap.fromImage(qimage)
        self._update_display()
    
    def set_blocks(self, blocks: List[Block]):
        """
        Установить список блоков для отображения
        
        Args:
            blocks: список блоков
        """
        self.current_blocks = blocks
        self._update_display()
    
    def _update_display(self):
        """Обновить отображение (изображение + блоки)"""
        if not self.page_image:
            return
        
        # Создаём копию изображения для рисования
        display_pixmap = self.page_image.copy()
        painter = QPainter(display_pixmap)
        
        # Рисуем существующие блоки
        for idx, block in enumerate(self.current_blocks):
            color = self._get_block_color(block.block_type)
            pen = QPen(color, 2)
            
            # Выделяем выбранный блок
            if idx == self.selected_block_idx:
                pen.setWidth(4)
            
            painter.setPen(pen)
            rect = QRect(block.x, block.y, block.width, block.height)
            painter.drawRect(rect)
        
        # Рисуем текущий создаваемый прямоугольник
        if self.current_rect:
            pen = QPen(QColor(255, 0, 0), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(self.current_rect)
        
        painter.end()
        
        # Отображаем
        self.image_label.setPixmap(display_pixmap)
    
    def _get_block_color(self, block_type: BlockType) -> QColor:
        """Получить цвет для типа блока"""
        colors = {
            BlockType.TEXT: QColor(0, 255, 0),      # зелёный
            BlockType.TABLE: QColor(0, 0, 255),     # синий
            BlockType.IMAGE: QColor(255, 165, 0)    # оранжевый
        }
        return colors.get(block_type, QColor(128, 128, 128))
    
    def mousePressEvent(self, event):
        """Обработка нажатия мыши"""
        if event.button() == Qt.LeftButton:
            # Проверяем, попали ли в существующий блок
            pos = self.image_label.mapFrom(self, event.pos())
            clicked_block = self._find_block_at_position(pos)
            
            if clicked_block is not None:
                self.selected_block_idx = clicked_block
                self.block_selected.emit(clicked_block)
                self._update_display()
            else:
                # Начинаем рисовать новый блок
                self.drawing = True
                self.start_point = pos
                self.current_rect = QRect(pos, pos)
    
    def mouseMoveEvent(self, event):
        """Обработка движения мыши"""
        if self.drawing and self.start_point:
            pos = self.image_label.mapFrom(self, event.pos())
            self.current_rect = QRect(self.start_point, pos).normalized()
            self._update_display()
    
    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши"""
        if event.button() == Qt.LeftButton and self.drawing:
            self.drawing = False
            
            if self.current_rect and self.current_rect.width() > 10 and self.current_rect.height() > 10:
                # Создаём новый блок
                block = Block(
                    x=self.current_rect.x(),
                    y=self.current_rect.y(),
                    width=self.current_rect.width(),
                    height=self.current_rect.height(),
                    block_type=BlockType.TEXT,  # по умолчанию
                    description=""
                )
                self.block_created.emit(block)
            
            self.current_rect = None
            self._update_display()
    
    def _find_block_at_position(self, pos: QPoint) -> Optional[int]:
        """
        Найти блок в заданной позиции
        
        Returns:
            Индекс блока или None
        """
        for idx, block in enumerate(self.current_blocks):
            rect = QRect(block.x, block.y, block.width, block.height)
            if rect.contains(pos):
                return idx
        return None

