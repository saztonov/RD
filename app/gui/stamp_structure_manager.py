"""
Управление структурой PDF для StampRemoverDialog
"""

import logging
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QLabel, QCheckBox, QPushButton, QMessageBox
from PySide6.QtCore import Qt
from app.pdf_structure import PDFElement, PDFElementType

logger = logging.getLogger(__name__)


class StampStructureManager:
    """Управление структурой PDF"""
    
    def __init__(self, parent, structure_tree: QTreeWidget, stats_label: QLabel,
                 show_annotations_cb: QCheckBox, show_images_cb: QCheckBox, show_forms_cb: QCheckBox):
        self.parent = parent
        self.structure_tree = structure_tree
        self.stats_label = stats_label
        self.show_annotations_cb = show_annotations_cb
        self.show_images_cb = show_images_cb
        self.show_forms_cb = show_forms_cb
    
    def update_tree(self):
        """Обновить дерево структуры"""
        try:
            logger.debug("[StampRemover] _update_tree: начало")
            self.structure_tree.clear()
            
            show_annots = self.show_annotations_cb.isChecked()
            show_images = self.show_images_cb.isChecked()
            show_forms = self.show_forms_cb.isChecked()
            
            total_count = 0
            
            for page_num in sorted(self.parent.page_elements.keys()):
                elements = self.parent.page_elements[page_num]
                
                filtered = []
                for elem in elements:
                    if elem.element_type == PDFElementType.ANNOTATION and show_annots:
                        filtered.append(elem)
                    elif elem.element_type == PDFElementType.IMAGE and show_images:
                        filtered.append(elem)
                    elif elem.element_type == PDFElementType.FORM and show_forms:
                        filtered.append(elem)
                
                if not filtered:
                    continue
                
                page_item = QTreeWidgetItem(self.structure_tree)
                page_item.setText(0, f"Страница {page_num + 1}")
                page_item.setText(1, f"({len(filtered)} элем.)")
                page_item.setData(0, Qt.UserRole, {"type": "page", "page_num": page_num})
                page_item.setCheckState(0, Qt.Unchecked)
                page_item.setExpanded(True)
                
                for elem in filtered:
                    elem_item = QTreeWidgetItem(page_item)
                    elem_item.setText(0, elem.name)
                    elem_item.setText(1, elem.element_type.value)
                    elem_item.setData(0, Qt.UserRole, {"type": "element", "element": elem})
                    
                    elem_key = (elem.page_num, elem.element_type, elem.index)
                    if elem_key in self.parent.checked_elements:
                        elem_item.setCheckState(0, Qt.Checked)
                    else:
                        elem_item.setCheckState(0, Qt.Unchecked)
                    
                    total_count += 1
            
            self.stats_label.setText(f"Всего элементов: {total_count} | Выбрано: {len(self.parent.checked_elements)}")
            logger.debug(f"[StampRemover] _update_tree: завершено, элементов: {total_count}")
        
        except Exception as e:
            logger.error(f"[StampRemover] Ошибка обновления дерева: {e}", exc_info=True)
            self.stats_label.setText(f"Ошибка: {e}")
    
    def count_total_elements(self) -> int:
        """Подсчитать общее количество элементов"""
        total = 0
        for elements in self.parent.page_elements.values():
            total += len(elements)
        return total
    
    def is_similar_element(self, elem1: PDFElement, elem2: PDFElement) -> bool:
        """Проверить, похожи ли два элемента"""
        if elem1.element_type != elem2.element_type:
            return False
        
        if elem1.element_type == PDFElementType.ANNOTATION:
            type1 = elem1.properties.get("type", "")
            type2 = elem2.properties.get("type", "")
            if type1 != type2:
                return False
        
        bbox1 = elem1.bbox
        bbox2 = elem2.bbox
        
        width1 = abs(bbox1[2] - bbox1[0])
        height1 = abs(bbox1[3] - bbox1[1])
        width2 = abs(bbox2[2] - bbox2[0])
        height2 = abs(bbox2[3] - bbox2[1])
        
        if width1 > 0 and height1 > 0 and width2 > 0 and height2 > 0:
            width_diff = abs(width1 - width2) / max(width1, width2)
            height_diff = abs(height1 - height2) / max(height1, height2)
            
            if width_diff > 0.1 or height_diff > 0.1:
                return False
        
        return True

