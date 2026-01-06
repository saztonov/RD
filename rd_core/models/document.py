"""
Модели документа и страницы PDF (legacy, для совместимости с GUI).
"""
from dataclasses import dataclass, field
from typing import List

from rd_core.models.block import Block


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
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: dict, migrate_ids: bool = True) -> tuple["Page", bool]:
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

        return (
            cls(
                page_number=page_num,
                width=data["width"],
                height=data["height"],
                blocks=blocks,
            ),
            was_migrated,
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
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict, migrate_ids: bool = True) -> tuple["Document", bool]:
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
                    pages.append(
                        Page(
                            page_number=i, width=ref.width, height=ref.height, blocks=[]
                        )
                    )
        else:
            pages = raw_pages

        return cls(pdf_path=data["pdf_path"], pages=pages), was_migrated
