"""
Управление рендерингом страниц для PageViewer
"""

import logging
from typing import Optional
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QBrush, QColor
from PySide6.QtCore import Qt, QRectF
from PIL import Image
from app.models import BlockType

logger = logging.getLogger(__name__)


class PageRenderManager:
    """Управление рендерингом страниц и блоков"""
    
    def __init__(self, parent):
        self.parent = parent
    
    def render_page_with_blocks(self, page_image: Image.Image) -> QPixmap:
        """Отрендерить страницу с блоками"""
        if not page_image:
            return QPixmap()
        
        image_rgb = page_image.convert("RGB")
        data = image_rgb.tobytes("raw", "RGB")
        qimage = QImage(data, image_rgb.width, image_rgb.height, 
                       image_rgb.width * 3, QImage.Format_RGB888)
        
        pixmap = QPixmap.fromImage(qimage)
        
        if self.parent.current_page_blocks:
            painter = QPainter(pixmap)
            
            for idx, block in enumerate(self.parent.current_page_blocks):
                x1, y1, x2, y2 = block.coords_px
                rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                
                color = self._get_block_color(block.block_type)
                
                if idx == self.parent.selected_block_idx:
                    pen = QPen(Qt.blue, 3, Qt.SolidLine)
                    brush = QBrush(QColor(0, 0, 255, 30))
                else:
                    pen = QPen(color, 2, Qt.SolidLine)
                    brush = QBrush(QColor(*color.toTuple()[:3], 30))
                
                painter.setPen(pen)
                painter.setBrush(brush)
                painter.drawRect(rect)
            
            painter.end()
        
        return pixmap
    
    def _get_block_color(self, block_type: BlockType) -> QColor:
        """Получить цвет для типа блока"""
        color_map = {
            BlockType.TEXT: QColor(0, 255, 0),
            BlockType.IMAGE: QColor(255, 0, 0),
            BlockType.TABLE: QColor(255, 165, 0),
        }
        return color_map.get(block_type, QColor(128, 128, 128))

