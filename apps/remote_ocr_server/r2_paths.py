"""Функции формирования путей в R2 Storage.

Новая структура:
    n/{node_id}/
        {doc_name}.pdf              # PDF документ
        {doc_stem}_result.md        # Markdown результат
        crops/
            {block_id}.pdf          # Кропы блоков

Метаданные блоков хранятся в Supabase (job_files.metadata, node_files.metadata).
"""
from pathlib import PurePosixPath


def get_doc_stem(doc_name: str) -> str:
    """Получить имя документа без расширения.

    Args:
        doc_name: Имя файла (например: "133-23-45.pdf")

    Returns:
        Имя без расширения (например: "133-23-45")
    """
    return PurePosixPath(doc_name).stem


def get_doc_prefix(node_id: str) -> str:
    """Префикс папки документа в R2.

    Args:
        node_id: UUID узла из tree_nodes

    Returns:
        Префикс вида "n/{node_id}"
    """
    return f"n/{node_id}"


def get_pdf_key(node_id: str, doc_name: str) -> str:
    """Ключ PDF файла в R2.

    Args:
        node_id: UUID узла
        doc_name: Имя файла (например: "133-23-45.pdf")

    Returns:
        Ключ вида "n/{node_id}/{doc_name}"
    """
    return f"n/{node_id}/{doc_name}"


def get_result_md_key(node_id: str, doc_name: str) -> str:
    """Ключ Markdown результата в R2.

    Args:
        node_id: UUID узла
        doc_name: Имя файла (например: "133-23-45.pdf")

    Returns:
        Ключ вида "n/{node_id}/{doc_stem}_result.md"
    """
    stem = get_doc_stem(doc_name)
    return f"n/{node_id}/{stem}_result.md"


def get_crop_key(node_id: str, block_id: str) -> str:
    """Ключ кропа блока в R2.

    Args:
        node_id: UUID узла
        block_id: ID блока (ArmorID)

    Returns:
        Ключ вида "n/{node_id}/crops/{block_id}.pdf"
    """
    return f"n/{node_id}/crops/{block_id}.pdf"


def get_crops_prefix(node_id: str) -> str:
    """Префикс папки кропов в R2.

    Args:
        node_id: UUID узла

    Returns:
        Префикс вида "n/{node_id}/crops/"
    """
    return f"n/{node_id}/crops/"
