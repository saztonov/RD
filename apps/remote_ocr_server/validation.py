"""Input validation for OCR jobs.

Validates PDF files and blocks JSON before processing.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Union

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

# PDF magic bytes - must be at start of file
PDF_MAGIC = b"%PDF"

# Size limits
MAX_PDF_SIZE = 500 * 1024 * 1024  # 500 MB
MIN_PDF_SIZE = 1024  # 1 KB (sanity check)
MAX_BLOCKS_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_BLOCKS_COUNT = 10000


class ValidationError(HTTPException):
    """Validation error with 400 status."""

    def __init__(self, detail: str):
        super().__init__(status_code=400, detail=detail)


async def validate_pdf_upload(
    upload_file: UploadFile,
    max_size: int = MAX_PDF_SIZE,
    check_magic: bool = True,
) -> int:
    """
    Validate PDF upload.

    Args:
        upload_file: FastAPI UploadFile
        max_size: Maximum allowed size in bytes
        check_magic: Whether to check PDF magic bytes

    Returns:
        File size in bytes

    Raises:
        ValidationError: If validation fails
    """
    # Get file size (use underlying file for full seek semantics)
    upload_file.file.seek(0, 2)  # SEEK_END
    file_size = upload_file.file.tell()
    upload_file.file.seek(0)

    # Size validation
    if file_size < MIN_PDF_SIZE:
        raise ValidationError(
            f"PDF file too small ({file_size} bytes). "
            f"Minimum size: {MIN_PDF_SIZE} bytes"
        )

    if file_size > max_size:
        size_mb = file_size / 1024 / 1024
        max_mb = max_size / 1024 / 1024
        raise ValidationError(
            f"PDF file too large ({size_mb:.1f} MB). "
            f"Maximum size: {max_mb:.0f} MB"
        )

    # Magic bytes validation
    if check_magic:
        header = await upload_file.read(8)
        await upload_file.seek(0)

        if not header.startswith(PDF_MAGIC):
            # Check for common mistakes
            if header.startswith(b"PK"):
                raise ValidationError(
                    "File appears to be a ZIP archive, not a PDF"
                )
            elif header.startswith(b"\x89PNG"):
                raise ValidationError(
                    "File appears to be a PNG image, not a PDF"
                )
            elif header.startswith(b"\xff\xd8\xff"):
                raise ValidationError(
                    "File appears to be a JPEG image, not a PDF"
                )
            elif header.startswith(b"GIF8"):
                raise ValidationError(
                    "File appears to be a GIF image, not a PDF"
                )
            else:
                hex_header = header[:4].hex()
                raise ValidationError(
                    f"Invalid PDF file: missing %PDF header. "
                    f"Got: 0x{hex_header}"
                )

    logger.debug(f"PDF validation passed: {file_size} bytes")
    return file_size


def validate_blocks_json(
    blocks_json: str,
    max_size: int = MAX_BLOCKS_SIZE,
    max_blocks: int = MAX_BLOCKS_COUNT,
) -> Dict[str, Any]:
    """
    Validate blocks JSON content.

    Args:
        blocks_json: JSON string
        max_size: Maximum allowed size in bytes
        max_blocks: Maximum allowed number of blocks

    Returns:
        Parsed blocks data (dict or list)

    Raises:
        ValidationError: If validation fails
    """
    # Size check
    json_bytes = blocks_json.encode("utf-8")
    if len(json_bytes) > max_size:
        size_mb = len(json_bytes) / 1024 / 1024
        max_mb = max_size / 1024 / 1024
        raise ValidationError(
            f"Blocks file too large ({size_mb:.1f} MB). "
            f"Maximum size: {max_mb:.0f} MB"
        )

    # JSON parsing
    try:
        data = json.loads(blocks_json)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON in blocks file: {e}")

    # Structure validation and block counting
    total_blocks = _count_blocks(data)

    if total_blocks == 0:
        logger.warning("Blocks file contains no blocks")

    if total_blocks > max_blocks:
        raise ValidationError(
            f"Too many blocks ({total_blocks}). Maximum: {max_blocks}"
        )

    logger.debug(f"Blocks validation passed: {total_blocks} blocks")
    return data


def _count_blocks(data: Union[Dict, List]) -> int:
    """Count total blocks in data structure."""
    if isinstance(data, dict):
        # annotation.json format with pages
        if "pages" in data:
            pages = data.get("pages", [])
            if not isinstance(pages, list):
                raise ValidationError(
                    "Invalid blocks format: 'pages' must be an array"
                )
            return sum(len(p.get("blocks", [])) for p in pages)
        # Single page or other dict format
        elif "blocks" in data:
            return len(data.get("blocks", []))
        else:
            raise ValidationError(
                "Invalid blocks format: expected 'pages' or 'blocks' array"
            )
    elif isinstance(data, list):
        # Legacy blocks array format
        return len(data)
    else:
        raise ValidationError(
            "Invalid blocks format: expected object or array"
        )


def validate_pdf_from_r2(
    s3_client,
    bucket_name: str,
    pdf_key: str,
    max_size: int = MAX_PDF_SIZE,
) -> int:
    """
    Validate PDF that was uploaded directly to R2.

    Args:
        s3_client: boto3 S3 client
        bucket_name: R2 bucket name
        pdf_key: R2 key for PDF
        max_size: Maximum allowed size

    Returns:
        File size in bytes

    Raises:
        ValidationError: If validation fails
    """
    try:
        head = s3_client.head_object(Bucket=bucket_name, Key=pdf_key)
    except Exception:
        raise ValidationError("PDF file not found in storage")

    file_size = head["ContentLength"]
    content_type = head.get("ContentType", "")

    if file_size < MIN_PDF_SIZE:
        raise ValidationError(
            f"PDF file too small ({file_size} bytes). "
            f"Minimum size: {MIN_PDF_SIZE} bytes"
        )

    if file_size > max_size:
        size_mb = file_size / 1024 / 1024
        max_mb = max_size / 1024 / 1024
        raise ValidationError(
            f"PDF file too large ({size_mb:.1f} MB). "
            f"Maximum size: {max_mb:.0f} MB"
        )

    # Content-Type check (warning only - client may not set it correctly)
    if content_type and "pdf" not in content_type.lower():
        logger.warning(
            f"PDF content-type mismatch: {content_type} for {pdf_key}"
        )

    return file_size
