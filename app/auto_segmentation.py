"""
Автоматическая сегментация блоков
Предложение блоков на основе анализа PDF (PyMuPDF + OpenCV)
"""

import cv2
import numpy as np
from PIL import Image
from typing import List, Tuple
from app.models import Block, BlockType


class AutoSegmentation:
    """
    Автоматическое выделение блоков на странице PDF
    """
    
    def __init__(self):
        """Инициализация параметров сегментации"""
        # Минимальные размеры блока (в пикселях)
        self.min_width = 50
        self.min_height = 50
    
    def suggest_blocks(self, page_image: Image.Image) -> List[Block]:
        """
        Предложить блоки для страницы на основе анализа изображения
        
        Args:
            page_image: изображение страницы
        
        Returns:
            Список предложенных блоков
        """
        try:
            # Конвертация PIL в OpenCV
            img_cv = self._pil_to_cv(page_image)
            
            # Поиск контуров
            contours = self._find_contours(img_cv)
            
            # Конвертация контуров в блоки
            blocks = self._contours_to_blocks(contours)
            
            return blocks
        except Exception as e:
            print(f"Ошибка автосегментации: {e}")
            return []
    
    def _pil_to_cv(self, pil_image: Image.Image) -> np.ndarray:
        """Конвертировать PIL Image в OpenCV формат"""
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    
    def _find_contours(self, img: np.ndarray) -> List:
        """
        Найти контуры на изображении
        
        Args:
            img: изображение в OpenCV формате
        
        Returns:
            Список контуров
        """
        # Конвертация в градации серого
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Бинаризация
        _, binary = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
        
        # Морфологические операции для удаления шума
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        
        # Поиск контуров
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        return contours
    
    def _contours_to_blocks(self, contours: List) -> List[Block]:
        """
        Конвертировать контуры в блоки
        
        Args:
            contours: список контуров OpenCV
        
        Returns:
            Список блоков
        """
        blocks = []
        
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            
            # Фильтрация по минимальным размерам
            if w >= self.min_width and h >= self.min_height:
                # Определяем тип блока по соотношению сторон (простая эвристика)
                block_type = self._guess_block_type(w, h)
                
                block = Block(
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    block_type=block_type,
                    description="Auto-detected",
                    is_auto=True
                )
                blocks.append(block)
        
        return blocks
    
    def _guess_block_type(self, width: int, height: int) -> BlockType:
        """
        Угадать тип блока по размерам (простая эвристика)
        
        Args:
            width: ширина блока
            height: высота блока
        
        Returns:
            Предполагаемый тип блока
        """
        aspect_ratio = width / height
        
        # Простые правила:
        # - квадратные/вертикальные блоки → изображения
        # - широкие длинные блоки → таблицы
        # - остальное → текст
        if 0.8 <= aspect_ratio <= 1.2:
            return BlockType.IMAGE
        elif aspect_ratio > 3.0:
            return BlockType.TABLE
        else:
            return BlockType.TEXT

