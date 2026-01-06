"""
Операции с node_files и tree_nodes (связь с деревом проектов).

DEPRECATED: Этот модуль перемещён в services.remote_ocr.server.storage.
Этот файл сохранён для обратной совместимости.
"""
# Реэкспорт из нового модуля
from services.remote_ocr.server.storage import (
    add_node_file,
    create_node,
    delete_node,
    delete_node_file,
    get_children,
    get_node,
    get_node_file_by_type,
    get_node_files,
    get_node_full_path,
    get_node_info,
    get_node_pdf_r2_key,
    get_root_nodes,
    register_ocr_results_to_node,
    update_node,
    update_node_pdf_status,
    update_node_r2_key,
    update_pdf_status,
)

__all__ = [
    "get_root_nodes",
    "get_node",
    "get_children",
    "create_node",
    "update_node",
    "delete_node",
    "update_pdf_status",
    "get_node_info",
    "get_node_full_path",
    "update_node_r2_key",
    "get_node_files",
    "delete_node_file",
    "get_node_file_by_type",
    "get_node_pdf_r2_key",
    "add_node_file",
    "register_ocr_results_to_node",
    "update_node_pdf_status",
]
