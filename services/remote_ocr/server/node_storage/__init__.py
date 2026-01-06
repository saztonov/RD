"""Модуль операций с хранилищем узлов и файлов"""
from services.remote_ocr.server.node_storage.file_manager import (
    add_node_file,
    delete_node_file,
    get_node_file_by_type,
    get_node_files,
    get_node_pdf_r2_key,
)
from services.remote_ocr.server.node_storage.ocr_registry import (
    register_ocr_results_to_node,
    update_node_pdf_status,
)
from services.remote_ocr.server.node_storage.repository import (
    create_node,
    delete_node,
    get_children,
    get_node,
    get_node_full_path,
    get_node_info,
    get_root_nodes,
    update_node,
    update_node_r2_key,
    update_pdf_status,
)

__all__ = [
    # Repository
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
    # File manager
    "get_node_files",
    "delete_node_file",
    "get_node_file_by_type",
    "get_node_pdf_r2_key",
    "add_node_file",
    # OCR registry
    "register_ocr_results_to_node",
    "update_node_pdf_status",
]
