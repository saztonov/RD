"""
Автоматическая сегментация блоков
Предложение блоков на основе анализа PDF (PyMuPDF + OpenCV)
"""

import cv2
import numpy as np
from PIL import Image
from typing import List, Tuple
from app.models import Block, BlockType, BlockSource


class AutoSegmentation:
    """
    Автоматическое выделение блоков на странице PDF
    """
    
    def __init__(self):
        """Инициализация параметров сегментации"""
        # Минимальные размеры блока (в пикселях)
        self.min_width = 50
        self.min_height = 50
    
    def suggest_blocks(self, page_image: Image.Image, category: str = "") -> List[Block]:
        """
        Предложить блоки для страницы на основе анализа изображения
        
        Args:
            page_image: изображение страницы
            category: категория для создаваемых блоков
        
        Returns:
            Список предложенных блоков
        """
        try:
            # Конвертация PIL в OpenCV
            img_cv = self._pil_to_cv(page_image)
            
            # Поиск контуров
            contours = self._find_contours(img_cv)
            
            # Конвертация контуров в блоки
            blocks = self._contours_to_blocks(contours, category)
            
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
    
    def _contours_to_blocks(self, contours: List, category: str = "") -> List[Block]:
        """
        Конвертировать контуры в блоки
        
        Args:
            contours: список контуров OpenCV
            category: категория для создаваемых блоков
        
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
                
                # Создание блока
                block = Block.create(
                    page_index=0,  # Заглушка, так как класс не знает о странице
                    coords_px=(x, y, x+w, y+h),
                    page_width=page_image.width,
                    page_height=page_image.height,
                    category=category,
                    block_type=block_type,
                    source=BlockSource.AUTO
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


def detect_blocks_from_image(page_image: Image.Image, page_index: int, min_area: int = 5000, category: str = "") -> List[Block]:
    """
    Обнаружение блоков на изображении с помощью OpenCV (морфология + контуры)
    
    Args:
        page_image: PIL изображение страницы
        page_index: индекс страницы
        min_area: минимальная площадь блока в пикселях
        category: категория для создаваемых блоков
    
    Returns:
        Список найденных блоков с source=AUTO
    """
    # Конвертация в grayscale numpy
    img_np = np.array(page_image.convert('L'))
    
    # Adaptive threshold для бинаризации
    binary = cv2.adaptiveThreshold(
        img_np, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY_INV, 11, 2
    )
    
    # Морфология: dilation + closing для объединения элементов
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    morph = cv2.dilate(binary, kernel, iterations=2)
    morph = cv2.morphologyEx(morph, cv2.MORPH_CLOSE, kernel, iterations=1)
    
    # Поиск контуров
    contours, _ = cv2.findContours(morph, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Создание блоков
    blocks = []
    page_width, page_height = page_image.size
    
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        
        # Фильтр по площади
        if area < min_area:
            continue
        
        # Координаты в формате (x1, y1, x2, y2)
        coords_px = (x, y, x + w, y + h)
        
        # Простая классификация по соотношению сторон
        # TODO: можно улучшить классификацию анализом содержимого:
        # - для TABLE: искать горизонтальные/вертикальные линии с помощью HoughLines
        # - для IMAGE: анализировать цветность, наличие градиентов
        # - для TEXT: детектить строки текста с помощью OCR или проекционных профилей
        aspect_ratio = w / h
        if aspect_ratio > 3.0:
            block_type = BlockType.TABLE
        elif 0.8 <= aspect_ratio <= 1.2:
            block_type = BlockType.IMAGE
        else:
            block_type = BlockType.TEXT
        
        # Создание блока
        block = Block.create(
            page_index=page_index,
            coords_px=coords_px,
            page_width=page_width,
            page_height=page_height,
            category=category,
            block_type=block_type,
            source=BlockSource.AUTO
        )
        blocks.append(block)
    
    return blocks

