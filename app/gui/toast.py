"""
Всплывающие уведомления (Toast)
"""

from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve


class Toast(QLabel):
    """Всплывающее уведомление"""
    
    def __init__(self, parent, message: str, duration: int = 2000, success: bool = True):
        super().__init__(message, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMaximumWidth(400)
        
        # Стиль
        if success:
            self.setStyleSheet("""
                QLabel {
                    background-color: #4CAF50;
                    color: white;
                    padding: 12px 24px;
                    border-radius: 8px;
                    font-size: 14px;
                }
            """)
        else:
            self.setStyleSheet("""
                QLabel {
                    background-color: #f44336;
                    color: white;
                    padding: 12px 24px;
                    border-radius: 8px;
                    font-size: 14px;
                }
            """)
        
        self.adjustSize()
        
        # Позиция (снизу по центру)
        parent_rect = parent.rect()
        x = (parent_rect.width() - self.width()) // 2
        y = parent_rect.height() - self.height() - 50
        self.move(x, y)
        
        # Анимация появления
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)
        
        self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(200)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.setEasingCurve(QEasingCurve.InOutQuad)
        
        self.fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(200)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QEasingCurve.InOutQuad)
        self.fade_out.finished.connect(self.deleteLater)
        
        # Показать
        self.show()
        self.fade_in.start()
        
        # Автоскрытие
        QTimer.singleShot(duration, self._start_fade_out)
    
    def _start_fade_out(self):
        self.fade_out.start()


def show_toast(parent, message: str, duration: int = 2000, success: bool = True):
    """Показать всплывающее уведомление"""
    Toast(parent, message, duration, success)

