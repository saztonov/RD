"""
Модель данных приложения
Содержит классы для представления страниц PDF и блоков разметки
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional
from enum import Enum

# Московский часовой пояс (UTC+3)
_MSK_TZ = timezone(timedelta(hours=3))


def get_moscow_time_str() -> str:
    """Получить текущее московское время в формате 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now(_MSK_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ArmorID алфавит (26 OCR-устойчивых символов)
_ARMOR_ALPHABET = "34679ACDEFGHJKLMNPQRTUVWXY"
_ARMOR_CHAR_MAP = {c: i for i, c in enumerate(_ARMOR_ALPHABET)}


def _num_to_base26(num: int, length: int) -> str:
    """Конвертировать число в base26 строку фиксированной длины."""
    if num == 0:
        return _ARMOR_ALPHABET[0] * length
    result = []
    while num > 0:
        result.append(_ARMOR_ALPHABET[num % 26])
        num //= 26
    while len(result) < length:
        result.append(_ARMOR_ALPHABET[0])
    return "".join(reversed(result[-length:]))


def _calculate_checksum(payload: str) -> str:
    """Вычислить 3-символьную контрольную сумму."""
    v1, v2, v3 = 0, 0, 0
    for i, char in enumerate(payload):
        val = _ARMOR_CHAR_MAP.get(char, 0)
        v1 += val
        v2 += val * (i + 3)
        v3 += val * (i + 7) * (i + 1)
    return (_ARMOR_ALPHABET[v1 % 26] + 
            _ARMOR_ALPHABET[v2 % 26] + 
            _ARMOR_ALPHABET[v3 % 26])


def generate_armor_id() -> str:
    """
    Генерировать уникальный ID блока в формате XXXX-XXXX-XXX.
    
    40 бит энтропии (8 символов payload) + 3 символа контрольной суммы.
    """
    # 40 бит = 5 байт
    random_bytes = secrets.token_bytes(5)
    num = int.from_bytes(random_bytes, 'big')
    
    payload = _num_to_base26(num, 8)
    checksum = _calculate_checksum(payload)
    full_code = payload + checksum
    return f"{full_code[:4]}-{full_code[4:8]}-{full_code[8:]}"


def is_armor_id(block_id: str) -> bool:
    """Проверить, является ли ID armor форматом (XXXX-XXXX-XXX)."""
    clean = block_id.replace("-", "").upper()
    return len(clean) == 11 and all(c in _ARMOR_ALPHABET for c in clean)


def uuid_to_armor_id(uuid_str: str) -> str:
    """Конвертировать UUID в armor ID формат."""
    clean = uuid_str.replace("-", "").lower()
    hex_prefix = clean[:10]
    num = int(hex_prefix, 16)
    payload = _num_to_base26(num, 8)
    checksum = _calculate_checksum(payload)
    full_code = payload + checksum
    return f"{full_code[:4]}-{full_code[4:8]}-{full_code[8:]}"


def migrate_block_id(block_id: str) -> tuple[str, bool]:
    """
    Мигрировать ID блока в armor формат если нужно.
    
    Returns: (new_id, was_migrated)
    """
    if is_armor_id(block_id):
        return block_id, False
    # Legacy UUID -> armor
    return uuid_to_armor_id(block_id), True


class BlockType(Enum):
    """Типы блоков разметки (2 типа: текст и картинка)"""
    TEXT = "text"
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
        block_type: тип блока (TEXT/IMAGE)
        source: источник создания (USER/AUTO)
        shape_type: тип формы (RECTANGLE/POLYGON)
        polygon_points: координаты вершин полигона [(x1,y1), (x2,y2), ...] для POLYGON
        image_file: путь к сохранённому кропу блока
        ocr_text: результат OCR распознавания
        prompt: промпт для OCR (dict с ключами system/user)
        hint: подсказка пользователя для IMAGE блока (описание содержимого)
        pdfplumber_text: сырой текст извлечённый pdfplumber для блока
        linked_block_id: ID связанного блока (для IMAGE+TEXT)
        group_id: ID группы блоков (None = общая группа)
        group_name: название группы (отображаемое пользователю)
        category_id: ID категории изображения (для IMAGE блоков)
        category_code: код категории изображения (для IMAGE блоков)
        created_at: дата и время создания блока (ISO формат)
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
    linked_block_id: Optional[str] = None  # ID связанного блока
    group_id: Optional[str] = None  # ID группы блоков
    group_name: Optional[str] = None  # Название группы
    category_id: Optional[str] = None  # ID категории изображения
    category_code: Optional[str] = None  # Код категории изображения (для сериализации)
    created_at: Optional[str] = None  # Дата создания (ISO формат)
    
    @staticmethod
    def generate_id() -> str:
        """Генерировать уникальный ID для блока в формате XXXX-XXXX-XXX"""
        return generate_armor_id()
    
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
               pdfplumber_text: Optional[str] = None,
               linked_block_id: Optional[str] = None) -> 'Block':
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
            linked_block_id: ID связанного блока
        
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
            pdfplumber_text=pdfplumber_text,
            linked_block_id=linked_block_id,
            created_at=get_moscow_time_str()
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
        if self.linked_block_id:
            result["linked_block_id"] = self.linked_block_id
        if self.group_id:
            result["group_id"] = self.group_id
        if self.group_name:
            result["group_name"] = self.group_name
        if self.category_id:
            result["category_id"] = self.category_id
        if self.category_code:
            result["category_code"] = self.category_code
        if self.created_at:
            result["created_at"] = self.created_at
        return result
    
    @classmethod
    def from_dict(cls, data: dict, migrate_ids: bool = True) -> tuple['Block', bool]:
        """
        Десериализация из словаря.
        
        Args:
            data: словарь с данными блока
            migrate_ids: мигрировать UUID в armor ID формат
        
        Returns:
            (Block, was_migrated) - блок и флаг миграции
        """
        # Безопасное получение block_type с fallback на TEXT
        # TABLE конвертируется в TEXT для обратной совместимости
        raw_type = data["block_type"]
        if raw_type == "table":
            block_type = BlockType.TEXT
        else:
            try:
                block_type = BlockType(raw_type)
            except ValueError:
                block_type = BlockType.TEXT
        
        # Безопасное получение shape_type с fallback на RECTANGLE
        try:
            shape_type = ShapeType(data.get("shape_type", "rectangle"))
        except ValueError:
            shape_type = ShapeType.RECTANGLE
        
        # Получение polygon_points если есть
        polygon_points = None
        if "polygon_points" in data and data["polygon_points"]:
            polygon_points = [tuple(p) for p in data["polygon_points"]]
        
        # Миграция ID
        was_migrated = False
        block_id = data["id"]
        linked_block_id = data.get("linked_block_id")
        group_id = data.get("group_id")
        
        if migrate_ids:
            block_id, m1 = migrate_block_id(block_id)
            was_migrated = m1
            
            if linked_block_id:
                linked_block_id, m2 = migrate_block_id(linked_block_id)
                was_migrated = was_migrated or m2
            
            if group_id:
                group_id, m3 = migrate_block_id(group_id)
                was_migrated = was_migrated or m3
        
        block = cls(
            id=block_id,
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
            pdfplumber_text=data.get("pdfplumber_text"),
            linked_block_id=linked_block_id,
            group_id=group_id,
            group_name=data.get("group_name"),
            category_id=data.get("category_id"),
            category_code=data.get("category_code"),
            created_at=data.get("created_at") or get_moscow_time_str()
        )
        return block, was_migrated


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
    def from_dict(cls, data: dict, migrate_ids: bool = True) -> tuple['Page', bool]:
        """
        Десериализация из словаря.
        
        Returns:
            (Page, was_migrated)
        """
        # Поддержка page_index из новой модели
        page_num = data.get("page_number")
        if page_num is None:
            page_num = data.get("page_index", 0)
        
        blocks = []
        was_migrated = False
        for b in data.get("blocks", []):
            block, migrated = Block.from_dict(b, migrate_ids)
            blocks.append(block)
            was_migrated = was_migrated or migrated
            
        return cls(
            page_number=page_num,
            width=data["width"],
            height=data["height"],
            blocks=blocks
        ), was_migrated


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
    def from_dict(cls, data: dict, migrate_ids: bool = True) -> tuple['Document', bool]:
        """
        Десериализация из словаря с поддержкой старого формата.
        
        Returns:
            (Document, was_migrated) - документ и флаг миграции ID
        """
        raw_pages = []
        was_migrated = False
        for p in data.get("pages", []):
            page, migrated = Page.from_dict(p, migrate_ids)
            raw_pages.append(page)
            was_migrated = was_migrated or migrated
        
        # Определяем, старый ли это формат (page_number != индекс массива)
        is_old_format = False
        if raw_pages:
            # Проверяем: первая страница начинается не с 0 или есть пропуски
            for idx, page in enumerate(raw_pages):
                if page.page_number != idx:
                    is_old_format = True
                    break
        
        if is_old_format and raw_pages:
            # Старый формат: создаём разреженный массив по page_number
            max_page = max(p.page_number for p in raw_pages)
            # Собираем страницы в dict по page_number
            pages_by_num = {p.page_number: p for p in raw_pages}
            
            # Создаём полный массив страниц
            pages = []
            for i in range(max_page + 1):
                if i in pages_by_num:
                    pages.append(pages_by_num[i])
                else:
                    # Берём размеры от ближайшей страницы
                    ref = raw_pages[0]
                    pages.append(Page(page_number=i, width=ref.width, height=ref.height, blocks=[]))
        else:
            pages = raw_pages
        
        return cls(pdf_path=data["pdf_path"], pages=pages), was_migrated

