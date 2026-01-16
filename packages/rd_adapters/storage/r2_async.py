"""Asynchronous R2 Storage implementation using aioboto3."""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from rd_adapters.storage.r2_sync import R2Config

logger = logging.getLogger(__name__)

# Chunk size for streaming operations
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


class R2AsyncStorage:
    """
    Asynchronous R2 storage client using aioboto3.

    Implements AsyncStoragePort protocol.
    """

    def __init__(self, config: R2Config):
        """
        Initialize R2 async storage.

        Args:
            config: R2 configuration
        """
        self.config = config
        self.bucket_name = config.bucket_name
        self._session = None

        try:
            import aioboto3
            self._aioboto3 = aioboto3
            logger.info(f"R2AsyncStorage initialized: {config.endpoint_url}")
        except ImportError:
            raise ImportError("aioboto3 required: pip install aioboto3")

    @classmethod
    def from_env(cls) -> "R2AsyncStorage":
        """Create instance from environment variables."""
        import os

        account_id = os.getenv("R2_ACCOUNT_ID")
        endpoint_url = os.getenv("R2_ENDPOINT_URL")

        if not endpoint_url and account_id:
            endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

        config = R2Config(
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

        return cls(config)

    def _get_session(self):
        """Get or create aioboto3 session."""
        if self._session is None:
            self._session = self._aioboto3.Session()
        return self._session

    def _guess_content_type(self, file_path: Path) -> str:
        """Determine MIME type by extension."""
        extension = file_path.suffix.lower()
        content_types = {
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
        return content_types.get(extension, "application/octet-stream")

    async def upload_file(
        self, local_path: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Upload file to R2 asynchronously."""
        try:
            local_file = Path(local_path)

            if not local_file.exists():
                logger.error(f"File not found: {local_path}")
                return False

            if content_type is None:
                content_type = self._guess_content_type(local_file)

            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                region_name=self.config.region,
            ) as client:
                file_size = local_file.stat().st_size

                # Use multipart for large files
                if file_size > CHUNK_SIZE:
                    await self._multipart_upload(
                        client, local_file, remote_key, content_type
                    )
                else:
                    with open(local_file, "rb") as f:
                        await client.put_object(
                            Bucket=self.bucket_name,
                            Key=remote_key,
                            Body=f.read(),
                            ContentType=content_type,
                        )

            logger.info(f"File uploaded to R2: {remote_key}")
            return True

        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return False

    async def _multipart_upload(
        self, client, local_file: Path, remote_key: str, content_type: str
    ):
        """Perform multipart upload for large files."""
        # Create multipart upload
        response = await client.create_multipart_upload(
            Bucket=self.bucket_name,
            Key=remote_key,
            ContentType=content_type,
        )
        upload_id = response["UploadId"]

        parts = []
        part_number = 1

        try:
            with open(local_file, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    part_response = await client.upload_part(
                        Bucket=self.bucket_name,
                        Key=remote_key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=chunk,
                    )

                    parts.append({
                        "PartNumber": part_number,
                        "ETag": part_response["ETag"],
                    })
                    part_number += 1

            # Complete multipart upload
            await client.complete_multipart_upload(
                Bucket=self.bucket_name,
                Key=remote_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )

        except Exception:
            # Abort on error
            await client.abort_multipart_upload(
                Bucket=self.bucket_name,
                Key=remote_key,
                UploadId=upload_id,
            )
            raise

    async def download_file(self, remote_key: str, local_path: str) -> bool:
        """Download file from R2 asynchronously."""
        try:
            local_file = Path(local_path)
            local_file.parent.mkdir(parents=True, exist_ok=True)

            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                region_name=self.config.region,
            ) as client:
                response = await client.get_object(
                    Bucket=self.bucket_name, Key=remote_key
                )

                # Stream download
                with open(local_file, "wb") as f:
                    async for chunk in response["Body"]:
                        f.write(chunk)

            logger.info(f"File downloaded from R2: {remote_key}")
            return True

        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return False

    async def upload_text(
        self, content: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Upload text content to R2 asynchronously."""
        try:
            if content_type is None:
                if remote_key.endswith(".json"):
                    content_type = "application/json; charset=utf-8"
                else:
                    content_type = "text/plain; charset=utf-8"

            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                region_name=self.config.region,
            ) as client:
                await client.put_object(
                    Bucket=self.bucket_name,
                    Key=remote_key,
                    Body=content.encode("utf-8"),
                    ContentType=content_type,
                )

            logger.info(f"Text uploaded to R2: {remote_key}")
            return True

        except Exception as e:
            logger.error(f"Error uploading text: {e}")
            return False

    async def download_text(self, remote_key: str) -> Optional[str]:
        """Download text content from R2 asynchronously."""
        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                region_name=self.config.region,
            ) as client:
                response = await client.get_object(
                    Bucket=self.bucket_name, Key=remote_key
                )
                content = await response["Body"].read()
                return content.decode("utf-8")

        except Exception as e:
            logger.error(f"Error downloading text: {e}")
            return None

    async def exists(self, remote_key: str) -> bool:
        """Check if object exists in R2 asynchronously."""
        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                region_name=self.config.region,
            ) as client:
                await client.head_object(Bucket=self.bucket_name, Key=remote_key)
                return True
        except Exception:
            return False

    async def delete_object(self, remote_key: str) -> bool:
        """Delete object from R2 asynchronously."""
        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                region_name=self.config.region,
            ) as client:
                await client.delete_object(Bucket=self.bucket_name, Key=remote_key)
            logger.info(f"Object deleted from R2: {remote_key}")
            return True
        except Exception as e:
            logger.error(f"Error deleting object: {e}")
            return False

    async def list_objects(self, prefix: str) -> List[str]:
        """List objects with given prefix asynchronously."""
        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                region_name=self.config.region,
            ) as client:
                response = await client.list_objects_v2(
                    Bucket=self.bucket_name, Prefix=prefix
                )
                return [obj["Key"] for obj in response.get("Contents", [])]
        except Exception as e:
            logger.error(f"Error listing objects: {e}")
            return []


class R2AsyncStorageSync:
    """
    Sync wrapper for R2AsyncStorage.

    Useful for Celery workers that need to use async storage
    from synchronous code.
    """

    def __init__(self, async_storage: R2AsyncStorage):
        self._async_storage = async_storage

    @classmethod
    def from_env(cls) -> "R2AsyncStorageSync":
        """Create instance from environment variables."""
        return cls(R2AsyncStorage.from_env())

    def _run(self, coro):
        """Run coroutine synchronously."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    def upload_file(
        self, local_path: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        return self._run(
            self._async_storage.upload_file(local_path, remote_key, content_type)
        )

    def download_file(self, remote_key: str, local_path: str) -> bool:
        return self._run(
            self._async_storage.download_file(remote_key, local_path)
        )

    def upload_text(
        self, content: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        return self._run(
            self._async_storage.upload_text(content, remote_key, content_type)
        )

    def download_text(self, remote_key: str) -> Optional[str]:
        return self._run(self._async_storage.download_text(remote_key))

    def exists(self, remote_key: str) -> bool:
        return self._run(self._async_storage.exists(remote_key))

    def delete_object(self, remote_key: str) -> bool:
        return self._run(self._async_storage.delete_object(remote_key))

    def list_objects(self, prefix: str) -> List[str]:
        return self._run(self._async_storage.list_objects(prefix))
