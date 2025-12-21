"""
Виджет просмотра страницы PDF
Отображение страницы с возможностью рисовать прямоугольники для разметки
"""

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsPolygonItem, QGraphicsTextItem, QGraphicsEllipseItem, QGraphicsLineItem
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPixmap, QPainter, QImage
from PIL import Image
from typing import Optional, List, Dict, Union
from rd_core.models import Block, ShapeType

from app.gui.page_viewer_polygon import PolygonMixin
from app.gui.page_viewer_resize import ResizeHandlesMixin
from app.gui.page_viewer_blocks import BlockRenderingMixin
from app.gui.page_viewer_mouse import MouseEventsMixin
from app.gui.page_viewer_context_menu import ContextMenuMixin


class PageViewer(ContextMenuMixin, MouseEventsMixin, BlockRenderingMixin, PolygonMixin, ResizeHandlesMixin, QGraphicsView):
    """
    Виджет для отображения страницы PDF и рисования блоков разметки
    """
    
    blockDrawn = Signal(int, int, int, int)
    polygonDrawn = Signal(list)
    block_selected = Signal(int)
    blocks_selected = Signal(list)
    blockEditing = Signal(int)
    blockDeleted = Signal(int)
    blocks_deleted = Signal(list)
    blockMoved = Signal(int, int, int, int, int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        self.page_image: Optional[QPixmap] = None
        self.image_item: Optional[QGraphicsPixmapItem] = None
        self.current_blocks: List[Block] = []
        self.block_items: Dict[str, Union[QGraphicsRectItem, QGraphicsPolygonItem]] = {}
        self.block_labels: Dict[str, QGraphicsTextItem] = {}
        self.resize_handles: List[QGraphicsRectItem] = []
        self.current_page: int = 0
        
        self.drawing = False
        self.drawing_polygon = False
        self.polygon_points: List[QPointF] = []
        self.polygon_preview_items: List[QGraphicsEllipseItem] = []
        self.polygon_line_items: List[QGraphicsLineItem] = []
        self.polygon_temp_line: Optional[QGraphicsLineItem] = None
        self.selecting = False
        self.right_button_pressed = False
        self.start_point: Optional[QPointF] = None
        self.rubber_band_item: Optional[QGraphicsRectItem] = None
        self.selected_block_idx: Optional[int] = None
        self.selected_block_indices: List[int] = []
        
        self.moving_block = False
        self.resizing_block = False
        self.resize_handle = None
        self.move_start_pos: Optional[QPointF] = None
        self.original_block_rect: Optional[QRectF] = None
        
        self.dragging_polygon_vertex: Optional[int] = None
        self.dragging_polygon_edge: Optional[int] = None
        self.original_polygon_points: Optional[List[tuple]] = None
        
        self.panning = False
        self.pan_start_pos: Optional[QPointF] = None
        
        self.zoom_factor = 1.0
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка интерфейса"""
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.context_menu_pos: Optional[QPointF] = None
    
    def get_current_shape_type(self) -> ShapeType:
        """Получить текущий выбранный тип формы из главного окна"""
        main_window = self.parent().window()
        if hasattr(main_window, 'selected_shape_type'):
            return main_window.selected_shape_type
        return ShapeType.RECTANGLE
    
    def _clamp_to_page(self, point: QPointF) -> QPointF:
        """Ограничить точку границами страницы"""
        if not self.page_image:
            return point
        page_rect = self.scene.sceneRect()
        x = max(page_rect.left(), min(point.x(), page_rect.right()))
        y = max(page_rect.top(), min(point.y(), page_rect.bottom()))
        return QPointF(x, y)
    
    def _clamp_rect_to_page(self, rect: QRectF) -> QRectF:
        """Ограничить прямоугольник границами страницы"""
        if not self.page_image:
            return rect
        page_rect = self.scene.sceneRect()
        x1 = max(page_rect.left(), min(rect.left(), page_rect.right()))
        y1 = max(page_rect.top(), min(rect.top(), page_rect.bottom()))
        x2 = max(page_rect.left(), min(rect.right(), page_rect.right()))
        y2 = max(page_rect.top(), min(rect.bottom(), page_rect.bottom()))
        if x2 - x1 < 10:
            x2 = min(x1 + 10, page_rect.right())
        if y2 - y1 < 10:
            y2 = min(y1 + 10, page_rect.bottom())
        return QRectF(QPointF(x1, y1), QPointF(x2, y2))
    
    def set_page_image(self, pil_image: Image.Image, page_number: int = 0, reset_zoom: bool = True):
        """Установить изображение страницы"""
        if pil_image is None:
            self.scene.clear()
            self.page_image = None
            self.image_item = None
            self.current_page = page_number
            self.selected_block_idx = None
            self.block_items.clear()
            return
        
        img_bytes = pil_image.tobytes("raw", "RGB")
        qimage = QImage(img_bytes, pil_image.width, pil_image.height, 
                       pil_image.width * 3, QImage.Format_RGB888)
        self.page_image = QPixmap.fromImage(qimage)
        self.current_page = page_number
        
        self.scene.clear()
        self.image_item = self.scene.addPixmap(self.page_image)
        self.scene.setSceneRect(QRectF(self.page_image.rect()))
        
        self.selected_block_idx = None
        self.selected_block_indices = []
        self.block_items.clear()
        self.block_labels.clear()
        
        if reset_zoom:
            self.fit_to_view()
    
    def reset_zoom(self):
        """Сбросить масштаб к 100%"""
        self.resetTransform()
        self.zoom_factor = 1.0
    
    def fit_to_view(self):
        """Подогнать страницу под размер view"""
        if self.page_image:
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            self.zoom_factor = self.transform().m11()
    