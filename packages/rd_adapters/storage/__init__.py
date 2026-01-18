"""R2 Storage adapters - sync and async implementations."""

from rd_adapters.storage.errors import (
    StorageErrorCode,
    StorageErrorResult,
    classify_client_error,
    handle_download_error,
    handle_upload_error,
)
from rd_adapters.storage.ports import AsyncStoragePort, StoragePort
from rd_adapters.storage.r2_async import R2AsyncStorage, R2AsyncStorageSync
from rd_adapters.storage.r2_sync import (
    CONTENT_TYPES,
    R2Config,
    R2SyncStorage,
    guess_content_type,
)

__all__ = [
    # Ports (protocols)
    "StoragePort",
    "AsyncStoragePort",
    # Config and utils
    "R2Config",
    "CONTENT_TYPES",
    "guess_content_type",
    # Sync implementation
    "R2SyncStorage",
    # Async implementation
    "R2AsyncStorage",
    "R2AsyncStorageSync",
    # Error handling
    "StorageErrorCode",
    "StorageErrorResult",
    "classify_client_error",
    "handle_download_error",
    "handle_upload_error",
]
