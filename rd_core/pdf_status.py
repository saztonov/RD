"""Утилиты для работы со статусами PDF документов"""
import json
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class PDFStatus(str, Enum):
    """Статус PDF документа"""
    COMPLETE = "complete"              # Все файлы есть, блоки размечены
    MISSING_FILES = "missing_files"    # Не хватает файлов
    MISSING_BLOCKS = "missing_blocks"  # Нет annotation или есть страницы без блоков
    UNKNOWN = "unknown"                # Статус неизвестен


def calculate_pdf_status(
    r2_storage,
    node_id: str,
    r2_key: str,
    check_blocks: bool = True
) -> tuple[PDFStatus, str]:
    """
    Вычислить статус PDF документа
    
    Args:
        r2_storage: Экземпляр R2Storage
        node_id: ID узла документа
        r2_key: R2 ключ PDF файла
        check_blocks: Проверять ли наличие блоков в annotation.json
        
    Returns:
        Кортеж (статус, сообщение)
    """
    from pathlib import PurePosixPath
    from app.tree_client import TreeClient, FileType
    
    if not r2_key:
        return PDFStatus.UNKNOWN, "Нет R2 ключа"
    
    try:
        client = TreeClient()
        
        # Формируем ключи для связанных файлов
        pdf_path = PurePosixPath(r2_key)
        pdf_stem = pdf_path.stem
        pdf_parent = str(pdf_path.parent)
        
        ann_r2_key = f"{pdf_parent}/{pdf_stem}_annotation.json"
        ocr_r2_key = f"{pdf_parent}/{pdf_stem}_ocr.html"
        res_r2_key = f"{pdf_parent}/{pdf_stem}_result.json"
        
        # Проверяем наличие файлов на R2
        has_annotation_r2 = r2_storage.exists(ann_r2_key)
        has_ocr_html_r2 = r2_storage.exists(ocr_r2_key)
        has_result_json_r2 = r2_storage.exists(res_r2_key)
        
        # Проверяем наличие файлов в Supabase
        node_files = client.get_node_files(node_id)
        file_types_in_db = {nf.file_type for nf in node_files}
        
        has_annotation_db = FileType.ANNOTATION in file_types_in_db
        has_ocr_html_db = FileType.OCR_HTML in file_types_in_db
        has_result_json_db = FileType.RESULT_JSON in file_types_in_db
        
        # Проверяем блоки если требуется
        pages_without_blocks = []
        if check_blocks and has_annotation_r2:
            try:
                ann_content = r2_storage.download_text(ann_r2_key)
                if ann_content:
                    ann_data = json.loads(ann_content)
                    pages = ann_data.get("pages", [])
                    
                    for page in pages:
                        page_num = page.get("page_number", -1)
                        blocks = page.get("blocks", [])
                        if not blocks:
                            pages_without_blocks.append(page_num)
            except Exception as e:
                logger.error(f"Failed to parse annotation.json: {e}")
        
        # Определяем статус и сообщение
        missing_r2 = []
        missing_db = []
        
        if not has_annotation_r2:
            missing_r2.append("annotation.json")
        if not has_annotation_db:
            missing_db.append("annotation.json")
        if not has_ocr_html_r2:
            missing_r2.append("ocr.html")
        if not has_ocr_html_db:
            missing_db.append("ocr.html")
        if not has_result_json_r2:
            missing_r2.append("result.json")
        if not has_result_json_db:
            missing_db.append("result.json")
        
        # Приоритет 3: Нет annotation.json или есть страницы без блоков
        if not has_annotation_r2:
            return PDFStatus.MISSING_BLOCKS, "Нет annotation.json на R2"
        elif pages_without_blocks:
            pages_str = ", ".join(str(p) for p in sorted(pages_without_blocks))
            return PDFStatus.MISSING_BLOCKS, f"Страницы без блоков: {pages_str}"
        # Приоритет 2: Не хватает файлов
        elif missing_r2 or missing_db:
            parts = []
            if missing_r2:
                parts.append(f"R2: {', '.join(missing_r2)}")
            if missing_db:
                parts.append(f"БД: {', '.join(missing_db)}")
            message = "Отсутствует:\n" + "\n".join(parts)
            return PDFStatus.MISSING_FILES, message
        # Приоритет 1: Всё в порядке
        else:
            return PDFStatus.COMPLETE, "Все файлы на месте, блоки размечены"
            
    except Exception as e:
        logger.error(f"Failed to calculate PDF status: {e}")
        return PDFStatus.UNKNOWN, f"Ошибка проверки: {e}"


def update_pdf_status_in_db(client, node_id: str, status: PDFStatus, message: str = None):
    """
    Обновить статус PDF в БД
    
    Args:
        client: TreeClient
        node_id: ID узла документа
        status: Статус
        message: Сообщение (опционально)
    """
    try:
        # Используем RPC функцию для обновления
        response = client._request(
            "post",
            "/rpc/update_pdf_status",
            json={
                "p_node_id": node_id,
                "p_status": status.value,
                "p_message": message
            }
        )
        logger.debug(f"Updated PDF status for {node_id}: {status.value}")
    except Exception as e:
        logger.error(f"Failed to update PDF status in DB: {e}")
