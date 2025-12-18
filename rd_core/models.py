"""
Модель данных приложения
Содержит классы для представления страниц PDF и блоков разметки
"""

import uuid
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum
from PIL import Image


class BlockType(Enum):
    """Типы блоков разметки (3 основных типа)"""
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class BlockSource(Enum):
    """Источник создания блока"""
    USER = "user"    # Создан пользователем вручную
    AUTO = "auto"    # Создан автоматической сегментацией


class ShapeType(Enum):
    """Тип формы блока"""
    RECTANGLE = "rectangle"  # Прямоугольник
    POLYGON = "polygon"      # Многоугольник


@dataclass
class Block:
    """
    Блок разметки на странице PDF (обновлённая версия)
    
    Attributes:
        id: уникальный идентификатор блока (UUID)
        page_index: индекс страницы (начиная с 0)
        coords_px: координаты в пикселях (x1, y1, x2, y2) на отрендеренном изображении
        coords_norm: нормализованные координаты (0..1) относительно ширины/высоты
        block_type: тип блока (TEXT/TABLE/IMAGE)
        source: источник создания (USER/AUTO)
        shape_type: тип формы (RECTANGLE/POLYGON)
        polygon_points: координаты вершин полигона [(x1,y1), (x2,y2), ...] для POLYGON
        image_file: путь к сохранённому кропу блока
        ocr_text: результат OCR распознавания
        prompt: промпт для OCR (dict с ключами system/user)
        hint: подсказка пользователя для IMAGE блока (описание содержимого)
        pdfplumber_text: сырой текст извлечённый pdfplumber для блока
    """
    id: str
    page_index: int
    coords_px: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    coords_norm: Tuple[float, float, float, float]  # (x1, y1, x2, y2) в диапазоне 0..1
    block_type: BlockType
    source: BlockSource
    shape_type: ShapeType = ShapeType.RECTANGLE
    polygon_points: Optional[List[Tuple[int, int]]] = None  # Для полигонов
    image_file: Optional[str] = None
    ocr_text: Optional[str] = None
    prompt: Optional[dict] = None  # {"system": "...", "user": "..."}
    hint: Optional[str] = None  # Подсказка пользователя для IMAGE блока
    pdfplumber_text: Optional[str] = None  # Сырой текст pdfplumber
    
    @staticmethod
    def generate_id() -> str:
        """Генерировать уникальный ID для блока"""
        return str(uuid.uuid4())
    
    @staticmethod
    def px_to_norm(coords_px: Tuple[int, int, int, int], 
                   page_width: int, 
                   page_height: int) -> Tuple[float, float, float, float]:
        """
        Конвертировать координаты из пикселей в нормализованные (0..1)
        
        Args:
            coords_px: координаты в пикселях (x1, y1, x2, y2)
            page_width: ширина страницы в пикселях
            page_height: высота страницы в пикселях
        
        Returns:
            Нормализованные координаты (x1, y1, x2, y2)
        """
        x1, y1, x2, y2 = coords_px
        return (
            x1 / page_width,
            y1 / page_height,
            x2 / page_width,
            y2 / page_height
        )
    
    @staticmethod
    def norm_to_px(coords_norm: Tuple[float, float, float, float],
                   page_width: int,
                   page_height: int) -> Tuple[int, int, int, int]:
        """
        Конвертировать нормализованные координаты (0..1) в пиксели
        
        Args:
            coords_norm: нормализованные координаты (x1, y1, x2, y2)
            page_width: ширина страницы в пикселях
            page_height: высота страницы в пикселях
        
        Returns:
            Координаты в пикселях (x1, y1, x2, y2)
        """
        x1, y1, x2, y2 = coords_norm
        return (
            int(x1 * page_width),
            int(y1 * page_height),
            int(x2 * page_width),
            int(y2 * page_height)
        )
    
    @classmethod
    def create(cls,
               page_index: int,
               coords_px: Tuple[int, int, int, int],
               page_width: int,
               page_height: int,
               block_type: BlockType,
               source: BlockSource,
               shape_type: ShapeType = ShapeType.RECTANGLE,
               polygon_points: Optional[List[Tuple[int, int]]] = None,
               image_file: Optional[str] = None,
               ocr_text: Optional[str] = None,
               block_id: Optional[str] = None,
               prompt: Optional[dict] = None,
               hint: Optional[str] = None,
               pdfplumber_text: Optional[str] = None) -> 'Block':
        """
        Создать блок с автоматическим вычислением нормализованных координат
        
        Args:
            page_index: индекс страницы
            coords_px: координаты в пикселях (x1, y1, x2, y2)
            page_width: ширина страницы в пикселях
            page_height: высота страницы в пикселях
            block_type: тип блока
            source: источник создания
            shape_type: тип формы (прямоугольник/полигон)
            polygon_points: вершины полигона
            image_file: путь к кропу
            ocr_text: результат OCR
            block_id: ID блока (если None, генерируется автоматически)
            prompt: промпт для OCR
            hint: подсказка пользователя для IMAGE блока
            pdfplumber_text: сырой текст pdfplumber
        
        Returns:
            Новый экземпляр Block
        """
        coords_norm = cls.px_to_norm(coords_px, page_width, page_height)
        
        return cls(
            id=block_id or cls.generate_id(),
            page_index=page_index,
            coords_px=coords_px,
            coords_norm=coords_norm,
            block_type=block_type,
            source=source,
            shape_type=shape_type,
            polygon_points=polygon_points,
            image_file=image_file,
            ocr_text=ocr_text,
            prompt=prompt,
            hint=hint,
            pdfplumber_text=pdfplumber_text
        )
    
    def get_width_height_px(self) -> Tuple[int, int]:
        """Получить ширину и высоту блока в пикселях"""
        x1, y1, x2, y2 = self.coords_px
        return (x2 - x1, y2 - y1)
    
    def get_width_height_norm(self) -> Tuple[float, float]:
        """Получить ширину и высоту блока в нормализованных координатах"""
        x1, y1, x2, y2 = self.coords_norm
        return (x2 - x1, y2 - y1)
    
    def update_coords_px(self, new_coords_px: Tuple[int, int, int, int],
                        page_width: int, page_height: int):
        """
        Обновить координаты в пикселях и пересчитать нормализованные
        
        Args:
            new_coords_px: новые координаты в пикселях
            page_width: ширина страницы
            page_height: высота страницы
        """
        self.coords_px = new_coords_px
        self.coords_norm = self.px_to_norm(new_coords_px, page_width, page_height)
    
    def to_dict(self) -> dict:
        """Сериализация в словарь для JSON"""
        result = {
            "id": self.id,
            "page_index": self.page_index,
            "coords_px": list(self.coords_px),
            "coords_norm": list(self.coords_norm),
            "block_type": self.block_type.value,
            "source": self.source.value,
            "shape_type": self.shape_type.value,
            "image_file": self.image_file,
            "ocr_text": self.ocr_text
        }
        if self.polygon_points:
            result["polygon_points"] = [list(p) for p in self.polygon_points]
        if self.prompt:
            result["prompt"] = self.prompt
        if self.hint:
            result["hint"] = self.hint
        if self.pdfplumber_text:
            result["pdfplumber_text"] = self.pdfplumber_text
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Block':
        """Десериализация из словаря"""
        # Безопасное получение block_type с fallback на TEXT
        try:
            block_type = BlockType(data["block_type"])
        except ValueError:
            block_type = BlockType.TEXT  # Fallback для неизвестных типов
        
        # Безопасное получение shape_type с fallback на RECTANGLE
        try:
            shape_type = ShapeType(data.get("shape_type", "rectangle"))
        except ValueError:
            shape_type = ShapeType.RECTANGLE
        
        # Получение polygon_points если есть
        polygon_points = None
        if "polygon_points" in data and data["polygon_points"]:
            polygon_points = [tuple(p) for p in data["polygon_points"]]
        
        return cls(
            id=data["id"],
            page_index=data["page_index"],
            coords_px=tuple(data["coords_px"]),
            coords_norm=tuple(data["coords_norm"]),
            block_type=block_type,
            source=BlockSource(data["source"]),
            shape_type=shape_type,
            polygon_points=polygon_points,
            image_file=data.get("image_file"),
            ocr_text=data.get("ocr_text"),
            prompt=data.get("prompt"),
            hint=data.get("hint"),
            pdfplumber_text=data.get("pdfplumber_text")
        )


@dataclass
class PageModel:
    """
    Модель страницы PDF с изображением и блоками (обновлённая версия)
    
    Attributes:
        page_index: индекс страницы (начиная с 0)
        image: отрендеренное изображение страницы (PIL.Image)
        blocks: список блоков разметки на этой странице
    """
    page_index: int
    image: Image.Image
    blocks: List[Block] = field(default_factory=list)
    
    @property
    def width(self) -> int:
        """Ширина страницы в пикселях"""
        return self.image.width
    
    @property
    def height(self) -> int:
        """Высота страницы в пикселях"""
        return self.image.height
    
    @property
    def size(self) -> Tuple[int, int]:
        """Размер страницы (ширина, высота)"""
        return self.image.size
    
    def add_block(self, block: Block):
        """Добавить блок на страницу"""
        self.blocks.append(block)
    
    def remove_block(self, block_id: str) -> bool:
        """
        Удалить блок по ID
        
        Returns:
            True если блок найден и удалён
        """
        for i, block in enumerate(self.blocks):
            if block.id == block_id:
                del self.blocks[i]
                return True
        return False
    
    def get_block_by_id(self, block_id: str) -> Optional[Block]:
        """Найти блок по ID"""
        for block in self.blocks:
            if block.id == block_id:
                return block
        return None
    
    def get_blocks_by_type(self, block_type: BlockType) -> List[Block]:
        """Получить все блоки заданного типа"""
        return [b for b in self.blocks if b.block_type == block_type]
    
    def get_blocks_by_source(self, source: BlockSource) -> List[Block]:
        """Получить все блоки из заданного источника"""
        return [b for b in self.blocks if b.source == source]
    
    def to_dict(self, include_image: bool = False) -> dict:
        """
        Сериализация в словарь для JSON
        
        Args:
            include_image: если True, включить данные изображения (base64)
        
        Note:
            По умолчанию изображение не сериализуется, т.к. оно может быть большим
        """
        result = {
            "page_index": self.page_index,
            "width": self.width,
            "height": self.height,
            "blocks": [block.to_dict() for block in self.blocks]
        }
        
        if include_image:
            import base64
            import io
            buffer = io.BytesIO()
            self.image.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            result["image_base64"] = img_base64
        
        return result


# ========== LEGACY КЛАССЫ ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ ==========

@dataclass
class Page:
    """
    Страница PDF с блоками разметки (legacy, для совместимости с GUI)
    
    Attributes:
        page_number: номер страницы (начиная с 0)
        width: ширина страницы в пикселях (после рендеринга)
        height: высота страницы в пикселях
        blocks: список блоков разметки на этой странице
    """
    page_number: int
    width: int
    height: int
    blocks: List[Block] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Сериализация в словарь для JSON"""
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "blocks": [block.to_dict() for block in self.blocks]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Page':
        """Десериализация из словаря"""
        # Поддержка page_index из новой модели
        page_num = data.get("page_number")
        if page_num is None:
            page_num = data.get("page_index", 0)
            
        return cls(
            page_number=page_num,
            width=data["width"],
            height=data["height"],
            blocks=[Block.from_dict(b) for b in data.get("blocks", [])]
        )


@dataclass
class Document:
    """
    PDF-документ с разметкой (legacy, для совместимости)
    
    Attributes:
        pdf_path: путь к PDF-файлу
        pages: список страниц с разметкой
    """
    pdf_path: str
    pages: List[Page] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Сериализация в словарь для JSON"""
        return {
            "pdf_path": self.pdf_path,
            "pages": [page.to_dict() for page in self.pages]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Document':
        """Десериализация из словаря"""
        return cls(
            pdf_path=data["pdf_path"],
            pages=[Page.from_dict(p) for p in data.get("pages", [])]
        )


# ========== HELPER ФУНКЦИИ ДЛЯ КОНВЕРТАЦИИ ==========


def block_to_legacy_coords(block: Block) -> Tuple[int, int, int, int]:
    """
    Конвертировать Block в legacy формат (x, y, width, height)
    
    Args:
        block: экземпляр Block
    
    Returns:
        (x, y, width, height)
    """
    x1, y1, x2, y2 = block.coords_px
    return (x1, y1, x2 - x1, y2 - y1)


def coords_xywh_to_xyxy(x: int, y: int, width: int, height: int) -> Tuple[int, int, int, int]:
    """
    Конвертировать координаты из формата (x, y, width, height) в (x1, y1, x2, y2)
    
    Args:
        x, y: координаты верхнего левого угла
        width, height: размеры
    
    Returns:
        (x1, y1, x2, y2)
    """
    return (x, y, x + width, y + height)


def coords_xyxy_to_xywh(x1: int, y1: int, x2: int, y2: int) -> Tuple[int, int, int, int]:
    """
    Конвертировать координаты из формата (x1, y1, x2, y2) в (x, y, width, height)
    
    Args:
        x1, y1: координаты верхнего левого угла
        x2, y2: координаты нижнего правого угла
    
    Returns:
        (x, y, width, height)
    """
    return (x1, y1, x2 - x1, y2 - y1)

