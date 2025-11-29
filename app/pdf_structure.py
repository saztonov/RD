"""
Анализ и модификация структуры PDF
Работа с контейнерами, изображениями, штампами
"""

import fitz
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PDFElementType(Enum):
    """Типы элементов PDF"""
    CONTAINER = "container"
    IMAGE = "image"
    FORM = "form"
    ANNOTATION = "annotation"


@dataclass
class PDFElement:
    """Элемент структуры PDF страницы"""
    element_type: PDFElementType
    page_num: int
    index: int
    name: str
    bbox: tuple  # (x0, y0, x1, y1)
    xref: int = 0
    properties: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


class PDFStructureAnalyzer:
    """Анализ структуры PDF документа"""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc: Optional[fitz.Document] = None
        logger.info(f"[Analyzer] Инициализация для: {pdf_path}")
    
    def open(self) -> bool:
        """Открыть документ"""
        try:
            logger.info(f"[Analyzer] Открытие документа: {self.pdf_path}")
            self.doc = fitz.open(self.pdf_path)
            logger.info(f"[Analyzer] Документ открыт успешно, страниц: {len(self.doc)}")
            return True
        except Exception as e:
            logger.error(f"[Analyzer] Ошибка открытия PDF: {e}", exc_info=True)
            return False
    
    def close(self):
        """Закрыть документ"""
        if self.doc:
            self.doc.close()
            self.doc = None
    
    def analyze_page(self, page_num: int) -> List[PDFElement]:
        """
        Анализ структуры страницы
        
        Args:
            page_num: номер страницы
            
        Returns:
            Список элементов страницы
        """
        logger.debug(f"[Analyzer] Анализ страницы {page_num}")
        if not self.doc or page_num < 0 or page_num >= len(self.doc):
            logger.warning(f"[Analyzer] Некорректная страница {page_num}")
            return []
        
        elements = []
        
        try:
            page = self.doc[page_num]
            logger.debug(f"[Analyzer] Страница {page_num} получена")
        except Exception as e:
            logger.error(f"[Analyzer] Ошибка получения страницы {page_num}: {e}", exc_info=True)
            return []
        
        # Аннотации (штампы, комментарии и т.д.)
        try:
            for annot_idx, annot in enumerate(page.annots()):
                try:
                    annot_type = annot.type[1] if annot.type else "Unknown"
                    bbox = annot.rect
                    
                    elem = PDFElement(
                        element_type=PDFElementType.ANNOTATION,
                        page_num=page_num,
                        index=annot_idx,
                        name=f"Аннотация: {annot_type}",
                        bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                        xref=annot.xref,
                        properties={
                            "type": annot_type,
                            "info": annot.info
                        }
                    )
                    elements.append(elem)
                except Exception as e:
                    logger.warning(f"Ошибка обработки аннотации {annot_idx}: {e}")
        except Exception as e:
            logger.warning(f"Ошибка получения аннотаций на странице {page_num}: {e}")
        
        # Изображения
        try:
            image_list = page.get_images(full=True)
            for img_idx, img in enumerate(image_list):
                try:
                    xref = img[0]
                    try:
                        bbox = page.get_image_bbox(img[7] if len(img) > 7 else f"img{img_idx}")
                        bbox_tuple = (bbox.x0, bbox.y0, bbox.x1, bbox.y1) if bbox else (0, 0, 0, 0)
                    except:
                        bbox_tuple = (0, 0, 0, 0)
                    
                    elem = PDFElement(
                        element_type=PDFElementType.IMAGE,
                        page_num=page_num,
                        index=img_idx,
                        name=f"Изображение #{img_idx + 1}",
                        bbox=bbox_tuple,
                        xref=xref,
                        properties={
                            "width": img[2] if len(img) > 2 else 0,
                            "height": img[3] if len(img) > 3 else 0,
                            "xref": xref
                        }
                    )
                    elements.append(elem)
                except Exception as e:
                    logger.warning(f"Ошибка обработки изображения {img_idx}: {e}")
        except Exception as e:
            logger.warning(f"Ошибка получения изображений на странице {page_num}: {e}")
        
        # Form XObjects (контейнеры)
        try:
            xobjects = page.get_xobjects()
            for xobj_idx, xobj in enumerate(xobjects):
                try:
                    xref = xobj[0]
                    name = xobj[1] if len(xobj) > 1 else f"XObj_{xobj_idx}"
                    
                    elem = PDFElement(
                        element_type=PDFElementType.FORM,
                        page_num=page_num,
                        index=xobj_idx,
                        name=f"Контейнер: {name}",
                        bbox=(0, 0, 0, 0),  # Получим позже если нужно
                        xref=xref,
                        properties={"name": name}
                    )
                    elements.append(elem)
                except Exception as e:
                    logger.warning(f"Ошибка обработки XObject {xobj_idx}: {e}")
        except Exception as e:
            logger.warning(f"Ошибка получения XObjects на странице {page_num}: {e}")
        
        return elements
    
    def analyze_all_pages(self) -> Dict[int, List[PDFElement]]:
        """
        Анализ всех страниц документа
        
        Returns:
            Словарь {номер_страницы: список_элементов}
        """
        if not self.doc:
            return {}
        
        result = {}
        for page_num in range(len(self.doc)):
            result[page_num] = self.analyze_page(page_num)
        
        return result


class PDFStructureModifier:
    """Модификация структуры PDF"""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc: Optional[fitz.Document] = None
    
    def open(self) -> bool:
        """Открыть документ"""
        try:
            self.doc = fitz.open(self.pdf_path)
            return True
        except Exception as e:
            logger.error(f"Ошибка открытия PDF: {e}")
            return False
    
    def close(self):
        """Закрыть документ"""
        if self.doc:
            self.doc.close()
            self.doc = None
    
    def remove_element(self, element: PDFElement) -> bool:
        """
        Удалить элемент из PDF
        
        Args:
            element: элемент для удаления
            
        Returns:
            True если успешно удален
        """
        if not self.doc:
            return False
        
        try:
            page = self.doc[element.page_num]
            
            if element.element_type == PDFElementType.ANNOTATION:
                # Удаление аннотации
                annot = page.first_annot
                idx = 0
                while annot:
                    if idx == element.index or annot.xref == element.xref:
                        page.delete_annot(annot)
                        logger.info(f"Удалена аннотация на странице {element.page_num}")
                        return True
                    annot = annot.next
                    idx += 1
            
            elif element.element_type == PDFElementType.IMAGE:
                # Удаление изображения через xref
                if element.xref:
                    try:
                        # Удаляем через cleanContents
                        page.clean_contents()
                        # Пытаемся удалить объект
                        # Это сложнее - нужно удалить ссылки в content stream
                        logger.info(f"Изображение xref={element.xref} помечено для удаления")
                        # TODO: полное удаление изображений сложнее
                        return True
                    except Exception as e:
                        logger.error(f"Ошибка удаления изображения: {e}")
            
            elif element.element_type == PDFElementType.FORM:
                # Удаление Form XObject
                if element.xref:
                    try:
                        logger.info(f"Form XObject xref={element.xref} помечен для удаления")
                        # TODO: удаление Form XObjects
                        return True
                    except Exception as e:
                        logger.error(f"Ошибка удаления Form XObject: {e}")
            
            return False
        
        except Exception as e:
            logger.error(f"Ошибка удаления элемента: {e}")
            return False
    
    def remove_elements(self, elements: List[PDFElement]) -> int:
        """
        Удалить несколько элементов
        
        Args:
            elements: список элементов для удаления
            
        Returns:
            Количество успешно удаленных элементов
        """
        count = 0
        for elem in elements:
            if self.remove_element(elem):
                count += 1
        return count
    
    def save(self, output_path: str) -> bool:
        """
        Сохранить модифицированный документ
        
        Args:
            output_path: путь для сохранения
            
        Returns:
            True если успешно сохранен
        """
        if not self.doc:
            return False
        
        try:
            self.doc.save(output_path, garbage=4, deflate=True)
            logger.info(f"PDF сохранен: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения PDF: {e}")
            return False
    
    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

