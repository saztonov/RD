"""Centralized error handling for storage operations."""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class StorageErrorCode(Enum):
    """Known storage error codes."""
    NOT_FOUND = "NoSuchKey"
    NOT_FOUND_404 = "404"
    TIMEOUT = "RequestTimeout"
    SERVICE_UNAVAILABLE = "ServiceUnavailable"
    UNKNOWN = "Unknown"


@dataclass
class StorageErrorResult:
    """Storage error classification result."""
    error_code: str
    error_message: str
    is_retryable: bool
    should_queue: bool


def classify_client_error(e: Exception) -> StorageErrorResult:
    """
    Classify storage client error and determine handling strategy.

    Args:
        e: Exception from storage client

    Returns:
        StorageErrorResult with error information
    """
    # Try to get error code from botocore ClientError
    error_code = "Unknown"
    error_message = str(e)

    if hasattr(e, 'response'):
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", str(e))

    # Not found errors
    if error_code in (StorageErrorCode.NOT_FOUND.value, StorageErrorCode.NOT_FOUND_404.value):
        return StorageErrorResult(
            error_code=error_code,
            error_message=error_message,
            is_retryable=False,
            should_queue=False
        )

    # Network errors - can retry
    if error_code in (StorageErrorCode.TIMEOUT.value, StorageErrorCode.SERVICE_UNAVAILABLE.value):
        return StorageErrorResult(
            error_code=error_code,
            error_message=error_message,
            is_retryable=True,
            should_queue=True
        )

    # Other errors
    return StorageErrorResult(
        error_code=error_code,
        error_message=error_message,
        is_retryable=False,
        should_queue=False
    )


def handle_download_error(
    e: Exception,
    remote_key: str,
    operation: str = "download"
) -> bool:
    """
    Handle storage download error.

    Args:
        e: Exception
        remote_key: Storage key
        operation: Operation name for logging

    Returns:
        True if error is handled (non-critical), False if critical
    """
    result = classify_client_error(e)

    if result.error_code in (StorageErrorCode.NOT_FOUND.value, StorageErrorCode.NOT_FOUND_404.value):
        logger.warning(f"File not found in storage: {remote_key}")
        return True

    if result.is_retryable:
        logger.warning(f"Network error during {operation}: {result.error_code}")
        return True

    if isinstance(e, (ConnectionError, TimeoutError)):
        logger.warning(f"Network error during {operation}: {e}")
        return True

    logger.error(f"Error during {operation}: {result.error_code} - {result.error_message}")
    return False


def handle_upload_error(
    e: Exception,
    remote_key: str,
    local_path: Optional[str] = None,
    operation: str = "upload"
) -> bool:
    """
    Handle storage upload error.

    Args:
        e: Exception
        remote_key: Storage key
        local_path: Local file path (for logging)
        operation: Operation name

    Returns:
        True if error is handled (non-critical), False if critical
    """
    result = classify_client_error(e)

    if result.is_retryable:
        logger.warning(f"Network error during {operation}: {result.error_message}")
        return True

    if isinstance(e, (ConnectionError, TimeoutError)):
        logger.warning(f"Network error during {operation}: {e}")
        return True

    logger.error(f"Error during {operation}: {result.error_code} - {result.error_message}")
    if local_path:
        logger.error(f"   File: {local_path}")
    logger.error(f"   Key: {remote_key}")
    return False
