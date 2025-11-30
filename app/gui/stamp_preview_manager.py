"""
Управление предпросмотром страниц для StampRemoverDialog
"""

import logging
from PySide6.QtWidgets import QLabel, QSpinBox, QPushButton, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from app.pdf_utils import PDFDocument

logger = logging.getLogger(__name__)


class StampPreviewManager:
    """Управление предпросмотром страниц"""
    
    def __init__(self, parent, preview_label: QLabel, page_spin: QSpinBox, page_label: QLabel,
                 prev_page_btn: QPushButton, next_page_btn: QPushButton):
        self.parent = parent
        self.preview_label = preview_label
        self.page_spin = page_spin
        self.page_label = page_label
        self.prev_page_btn = prev_page_btn
        self.next_page_btn = next_page_btn
    
    def show_preview_page(self, page_num: int):
        """Показать предпросмотр страницы"""
        try:
            logger.info(f"[StampRemover] Предпросмотр страницы {page_num}")
            pdf_doc = PDFDocument(self.parent.pdf_path)
            
            if pdf_doc.open():
                image = pdf_doc.render_page(page_num, zoom=1.5)
                
                if image:
                    image_rgb = image.convert("RGB")
                    data = image_rgb.tobytes("raw", "RGB")
                    qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format_RGB888)
                    qimage = qimage.copy()
                    
                    if qimage.isNull():
                        logger.error(f"[StampRemover] QImage NULL!")
                        self.preview_label.setText("Ошибка создания QImage")
                        pdf_doc.close()
                        return
                    
                    pixmap = QPixmap.fromImage(qimage)
                    scaled = pixmap.scaled(800, 1000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    
                    self.parent.current_preview_pixmap = pixmap
                    self.preview_label.setPixmap(scaled)
                    
                    if self.parent.highlighted_element and self.parent.highlighted_element.page_num == page_num:
                        self.redraw_preview_with_highlight()
                    
                    logger.info(f"[StampRemover] Предпросмотр отображен успешно")
                else:
                    self.preview_label.setText("Не удалось отрендерить страницу")
                
                pdf_doc.close()
            else:
                self.preview_label.setText("Не удалось открыть PDF")
        except Exception as e:
            logger.error(f"[StampRemover] КРИТИЧЕСКАЯ ОШИБКА предпросмотра страницы {page_num}: {e}", exc_info=True)
            try:
                self.preview_label.setText(f"Ошибка предпросмотра:\n{str(e)[:200]}")
            except:
                logger.error(f"[StampRemover] Не удалось даже установить текст ошибки!")
    
    def redraw_preview_with_highlight(self):
        """Перерисовать предпросмотр с подсветкой выделенного элемента"""
        if not self.parent.current_preview_pixmap or not self.parent.highlighted_element:
            return
        
        pixmap = self.parent.current_preview_pixmap.copy()
        painter = QPainter(pixmap)
        pen = QPen(QColor(255, 0, 0), 4)
        painter.setPen(pen)
        
        bbox = self.parent.highlighted_element.bbox
        x0, y0, x1, y1 = bbox
        
        zoom = 1.5
        rect_x = int(x0 * zoom)
        rect_y = int(y0 * zoom)
        rect_w = int((x1 - x0) * zoom)
        rect_h = int((y1 - y0) * zoom)
        
        painter.drawRect(rect_x, rect_y, rect_w, rect_h)
        painter.end()
        
        scaled = pixmap.scaled(800, 1000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)
    
    def prev_page(self):
        """Перейти на предыдущую страницу"""
        if self.parent.current_preview_page > 0:
            self.parent.current_preview_page -= 1
            self.page_spin.blockSignals(True)
            self.page_spin.setValue(self.parent.current_preview_page + 1)
            self.page_spin.blockSignals(False)
            if self.parent.highlighted_element and self.parent.highlighted_element.page_num != self.parent.current_preview_page:
                self.parent.highlighted_element = None
            self.show_preview_page(self.parent.current_preview_page)
            self.update_navigation_buttons()
    
    def next_page(self):
        """Перейти на следующую страницу"""
        if self.parent.current_preview_page < self.parent.total_pages - 1:
            self.parent.current_preview_page += 1
            self.page_spin.blockSignals(True)
            self.page_spin.setValue(self.parent.current_preview_page + 1)
            self.page_spin.blockSignals(False)
            if self.parent.highlighted_element and self.parent.highlighted_element.page_num != self.parent.current_preview_page:
                self.parent.highlighted_element = None
            self.show_preview_page(self.parent.current_preview_page)
            self.update_navigation_buttons()
    
    def on_page_changed(self, value: int):
        """Обработка изменения номера страницы"""
        new_page = value - 1
        if 0 <= new_page < self.parent.total_pages:
            if new_page != self.parent.current_preview_page:
                self.parent.current_preview_page = new_page
                if self.parent.highlighted_element and self.parent.highlighted_element.page_num != self.parent.current_preview_page:
                    self.parent.highlighted_element = None
                self.show_preview_page(self.parent.current_preview_page)
            self.update_navigation_buttons()
    
    def update_navigation_buttons(self):
        """Обновить состояние кнопок навигации"""
        self.prev_page_btn.setEnabled(self.parent.current_preview_page > 0)
        self.next_page_btn.setEnabled(self.parent.current_preview_page < self.parent.total_pages - 1)

