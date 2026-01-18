"""Synchronous R2 Storage implementation using boto3."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# Common content types for R2 uploads
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".html": "text/html",
}


def guess_content_type(file_path: Path) -> str:
    """Determine MIME type by extension."""
    extension = file_path.suffix.lower()
    return CONTENT_TYPES.get(extension, "application/octet-stream")


@dataclass
class R2Config:
    """Configuration for R2 storage."""
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    region: str = "auto"

    @classmethod
    def from_env(cls) -> "R2Config":
        """Create R2Config from environment variables."""
        account_id = os.getenv("R2_ACCOUNT_ID")
        endpoint_url = os.getenv("R2_ENDPOINT_URL")

        if not endpoint_url and account_id:
            endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

        config = cls(
            endpoint_url=endpoint_url or "",
            access_key_id=os.getenv("R2_ACCESS_KEY_ID", ""),
            secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", ""),
            bucket_name=os.getenv("R2_BUCKET_NAME", ""),
        )

        if not all([config.endpoint_url, config.access_key_id,
                    config.secret_access_key, config.bucket_name]):
            raise ValueError(
                "Missing R2 environment variables: "
                "R2_ENDPOINT_URL (or R2_ACCOUNT_ID), R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME"
            )

        return config


class R2SyncStorage:
    """
    Synchronous R2 storage client using boto3.

    Implements StoragePort protocol.
    """

    def __init__(self, config: Optional[R2Config] = None):
        """
        Initialize R2 sync storage.

        Args:
            config: R2 configuration
        """
        if config is None:
            config = R2Config.from_env()

        self.config = config
        self.bucket_name = config.bucket_name

        try:
            import boto3
            from botocore.config import Config
            from boto3.s3.transfer import TransferConfig

            # Config with retry
            boto_config = Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=30,
                read_timeout=60,
            )

            self.s3_client = boto3.client(
                "s3",
                endpoint_url=config.endpoint_url,
                aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key,
                config=boto_config,
                region_name=config.region,
            )

            # Transfer config for multipart
            self.transfer_config = TransferConfig(
                multipart_threshold=8 * 1024 * 1024,
                max_concurrency=20,
                multipart_chunksize=8 * 1024 * 1024,
                use_threads=True,
                max_io_queue=1000,
            )

            logger.info(f"R2SyncStorage initialized: {config.endpoint_url}")

        except ImportError:
            raise ImportError("boto3 required: pip install boto3")

    @classmethod
    def from_env(cls) -> "R2SyncStorage":
        """Create instance from environment variables."""
        return cls(R2Config.from_env())

    def upload_file(
        self, local_path: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Upload file to R2."""
        from rd_adapters.storage.errors import handle_upload_error

        try:
            local_file = Path(local_path)

            if not local_file.exists():
                logger.error(f"File not found: {local_path}")
                return False

            if content_type is None:
                content_type = guess_content_type(local_file)

            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            self.s3_client.upload_file(
                str(local_file),
                self.bucket_name,
                remote_key,
                ExtraArgs=extra_args,
                Config=self.transfer_config,
            )

            logger.info(f"File uploaded to R2: {remote_key}")
            return True

        except Exception as e:
            handle_upload_error(e, remote_key, local_path, "upload_file")
            return False

    def download_file(
        self, remote_key: str, local_path: str, use_cache: bool = True
    ) -> bool:
        """Download file from R2."""
        from rd_adapters.storage.errors import handle_download_error

        try:
            local_file = Path(local_path)
            local_file.parent.mkdir(parents=True, exist_ok=True)

            self.s3_client.download_file(
                self.bucket_name,
                remote_key,
                str(local_file),
                Config=self.transfer_config,
            )

            logger.info(f"File downloaded from R2: {remote_key}")
            return True

        except Exception as e:
            handle_download_error(e, remote_key, "download_file")
            return False

    def upload_text(
        self, content: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Upload text content to R2."""
        from rd_adapters.storage.errors import handle_upload_error

        try:
            if content_type is None:
                if remote_key.endswith(".json"):
                    content_type = "application/json; charset=utf-8"
                else:
                    content_type = "text/plain; charset=utf-8"

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=remote_key,
                Body=content.encode("utf-8"),
                ContentType=content_type,
            )

            logger.info(f"Text uploaded to R2: {remote_key}")
            return True

        except Exception as e:
            handle_upload_error(e, remote_key, None, "upload_text")
            return False

    def download_text(self, remote_key: str) -> Optional[str]:
        """Download text content from R2."""
        from rd_adapters.storage.errors import handle_download_error

        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name, Key=remote_key
            )
            content = response["Body"].read().decode("utf-8")
            logger.info(f"Text downloaded from R2: {remote_key}")
            return content

        except Exception as e:
            handle_download_error(e, remote_key, "download_text")
            return None

    def exists(self, remote_key: str, use_cache: bool = True) -> bool:
        """Check if object exists in R2."""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=remote_key)
            return True
        except Exception:
            return False

    def delete_object(self, remote_key: str) -> bool:
        """Delete object from R2."""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=remote_key)
            logger.info(f"Object deleted from R2: {remote_key}")
            return True
        except Exception as e:
            logger.error(f"Error deleting object: {e}")
            return False

    def list_objects(self, prefix: str) -> List[str]:
        """List objects with given prefix."""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name, Prefix=prefix
            )
            return [obj["Key"] for obj in response.get("Contents", [])]
        except Exception as e:
            logger.error(f"Error listing objects: {e}")
            return []

    def list_objects_with_metadata(
        self, prefix: str, use_cache: bool = True
    ) -> List[dict]:
        """List objects with metadata (Key, Size, ETag, LastModified)."""
        try:
            cache = None
            if use_cache:
                from rd_adapters.storage.caching import get_metadata_cache

                cache = get_metadata_cache()
                cached = cache.get_list(prefix)
                if cached is not None:
                    return cached

            objects: List[dict] = []
            continuation_token = None
            while True:
                kwargs = {"Bucket": self.bucket_name, "Prefix": prefix}
                if continuation_token:
                    kwargs["ContinuationToken"] = continuation_token

                response = self.s3_client.list_objects_v2(**kwargs)
                for obj in response.get("Contents", []):
                    etag = obj.get("ETag", "") or ""
                    if isinstance(etag, str):
                        etag = etag.strip('"')
                    objects.append(
                        {
                            "Key": obj.get("Key", ""),
                            "Size": obj.get("Size", 0) or 0,
                            "ETag": etag,
                            "LastModified": obj.get("LastModified"),
                        }
                    )

                if response.get("IsTruncated"):
                    continuation_token = response.get("NextContinuationToken")
                    if not continuation_token:
                        break
                else:
                    break

            if cache is not None:
                cache.set_list(prefix, objects)

            return objects
        except Exception as e:
            logger.error(f"Error listing objects with metadata: {e}")
            return []

    def generate_presigned_url(
        self, remote_key: str, expiration: int = 3600
    ) -> Optional[str]:
        """Generate presigned URL for object."""
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": remote_key},
                ExpiresIn=expiration,
            )
            return url
        except Exception as e:
            logger.error(f"Error generating presigned URL: {e}")
            return None

    def delete_objects_batch(self, keys: List[str]) -> tuple[List[str], List[str]]:
        """
        Delete multiple objects in batch.

        Args:
            keys: List of object keys to delete

        Returns:
            Tuple of (deleted_keys, failed_keys)
        """
        if not keys:
            return [], []

        deleted_keys: List[str] = []
        failed_keys: List[str] = []

        # S3 delete_objects supports max 1000 keys per request
        batch_size = 1000
        for i in range(0, len(keys), batch_size):
            batch = keys[i : i + batch_size]
            try:
                response = self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": False},
                )

                # Track deleted objects
                for obj in response.get("Deleted", []):
                    deleted_keys.append(obj["Key"])

                # Track errors
                for err in response.get("Errors", []):
                    failed_keys.append(err.get("Key", ""))
                    logger.error(f"Failed to delete {err.get('Key')}: {err.get('Message')}")

            except Exception as e:
                logger.error(f"Error in batch delete: {e}")
                failed_keys.extend(batch)

        if deleted_keys:
            logger.info(f"Batch deleted {len(deleted_keys)} objects from R2")

        return deleted_keys, failed_keys

    def delete_by_prefix(self, prefix: str) -> int:
        """Delete all objects with given prefix."""
        keys = self.list_objects(prefix)
        deleted = 0
        for key in keys:
            if self.delete_object(key):
                deleted += 1
        return deleted
