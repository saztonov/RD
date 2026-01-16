"""Storage port definitions - interfaces for storage implementations."""

from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class StoragePort(Protocol):
    """
    Unified storage interface for sync operations.

    Implementations: R2SyncStorage (boto3)
    """

    def upload_file(
        self, local_path: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Upload file to storage."""
        ...

    def download_file(
        self, remote_key: str, local_path: str, use_cache: bool = True
    ) -> bool:
        """Download file from storage."""
        ...

    def upload_text(
        self, content: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Upload text content to storage."""
        ...

    def download_text(self, remote_key: str) -> Optional[str]:
        """Download text content from storage."""
        ...

    def exists(self, remote_key: str, use_cache: bool = True) -> bool:
        """Check if object exists in storage."""
        ...

    def delete_object(self, remote_key: str) -> bool:
        """Delete object from storage."""
        ...

    def list_objects(self, prefix: str) -> List[str]:
        """List objects with given prefix."""
        ...

    def generate_presigned_url(
        self, remote_key: str, expiration: int = 3600
    ) -> Optional[str]:
        """Generate presigned URL for object."""
        ...


@runtime_checkable
class AsyncStoragePort(Protocol):
    """
    Unified storage interface for async operations.

    Implementations: R2AsyncStorage (aioboto3)
    """

    async def upload_file(
        self, local_path: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Upload file to storage."""
        ...

    async def download_file(
        self, remote_key: str, local_path: str
    ) -> bool:
        """Download file from storage."""
        ...

    async def upload_text(
        self, content: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Upload text content to storage."""
        ...

    async def download_text(self, remote_key: str) -> Optional[str]:
        """Download text content from storage."""
        ...

    async def exists(self, remote_key: str) -> bool:
        """Check if object exists in storage."""
        ...

    async def delete_object(self, remote_key: str) -> bool:
        """Delete object from storage."""
        ...

    async def list_objects(self, prefix: str) -> List[str]:
        """List objects with given prefix."""
        ...
