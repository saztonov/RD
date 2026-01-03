"""
Асинхронный Cloudflare R2 клиент на aioboto3
Для использования в Celery worker задачах через asyncio.run()
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional

from aiobotocore.config import AioConfig

logger = logging.getLogger(__name__)


class AsyncR2Storage:
    """Асинхронный клиент для R2 на aioboto3"""

    def __init__(
        self,
        account_id: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        self.account_id = account_id or os.getenv("R2_ACCOUNT_ID")
        self.access_key_id = access_key_id or os.getenv("R2_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = bucket_name or os.getenv("R2_BUCKET_NAME", "rd1")

        if endpoint_url:
            self.endpoint_url = endpoint_url
        elif self.account_id:
            self.endpoint_url = f"https://{self.account_id}.r2.cloudflarestorage.com"
        else:
            self.endpoint_url = os.getenv("R2_ENDPOINT_URL")

        if not all([self.access_key_id, self.secret_access_key, self.endpoint_url]):
            raise ValueError("R2 credentials not configured")

        self._config = AioConfig(
            connect_timeout=30,
            read_timeout=120,
            retries={"max_attempts": 5, "mode": "adaptive"},
        )

    def _get_session(self):
        import aioboto3

        return aioboto3.Session()

    async def download_file(self, remote_key: str, local_path: str) -> bool:
        """Асинхронно скачать файл из R2"""
        try:
            local_file = Path(local_path)
            local_file.parent.mkdir(parents=True, exist_ok=True)

            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=self._config,
            ) as client:
                response = await client.get_object(
                    Bucket=self.bucket_name, Key=remote_key
                )

                # Streaming download
                body = response["Body"]
                data = await body.read()
                with open(local_file, "wb") as f:
                    f.write(data)

            logger.debug(f"✅ Async download: {remote_key}")
            return True

        except Exception as e:
            logger.error(f"❌ Async download error {remote_key}: {e}")
            return False

    async def upload_file(
        self, local_path: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Асинхронно загрузить файл в R2"""
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
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=self._config,
            ) as client:
                # Streaming upload
                with open(local_file, "rb") as f:
                    await client.put_object(
                        Bucket=self.bucket_name,
                        Key=remote_key,
                        Body=f.read(),
                        ContentType=content_type,
                    )

            logger.debug(f"✅ Async upload: {remote_key}")
            return True

        except Exception as e:
            logger.error(f"❌ Async upload error {remote_key}: {e}")
            return False

    async def download_text(self, remote_key: str) -> Optional[str]:
        """Асинхронно скачать текст из R2"""
        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=self._config,
            ) as client:
                response = await client.get_object(
                    Bucket=self.bucket_name, Key=remote_key
                )
                async with response["Body"] as stream:
                    data = await stream.read()
                    return data.decode("utf-8")
        except Exception as e:
            logger.error(f"❌ Async download_text error {remote_key}: {e}")
            return None

    async def upload_text(
        self, content: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        """Асинхронно загрузить текст в R2"""
        try:
            if content_type is None:
                if remote_key.endswith(".json"):
                    content_type = "application/json; charset=utf-8"
                else:
                    content_type = "text/plain; charset=utf-8"

            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=self._config,
            ) as client:
                await client.put_object(
                    Bucket=self.bucket_name,
                    Key=remote_key,
                    Body=content.encode("utf-8"),
                    ContentType=content_type,
                )
            return True
        except Exception as e:
            logger.error(f"❌ Async upload_text error {remote_key}: {e}")
            return False

    async def exists(self, remote_key: str) -> bool:
        """Проверить существование объекта"""
        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=self._config,
            ) as client:
                await client.head_object(Bucket=self.bucket_name, Key=remote_key)
                return True
        except Exception:
            return False

    async def delete_object(self, remote_key: str) -> bool:
        """Удалить объект"""
        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=self._config,
            ) as client:
                await client.delete_object(Bucket=self.bucket_name, Key=remote_key)
            return True
        except Exception as e:
            logger.error(f"❌ Async delete error {remote_key}: {e}")
            return False

    async def list_objects(self, prefix: str = "") -> List[str]:
        """Список объектов по префиксу"""
        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=self._config,
            ) as client:
                response = await client.list_objects_v2(
                    Bucket=self.bucket_name, Prefix=prefix
                )
                if "Contents" not in response:
                    return []
                return [obj["Key"] for obj in response["Contents"]]
        except Exception as e:
            logger.error(f"❌ Async list error: {e}")
            return []

    def _guess_content_type(self, file_path: Path) -> str:
        ext = file_path.suffix.lower()
        types = {
            ".pdf": "application/pdf",
            ".json": "application/json",
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        return types.get(ext, "application/octet-stream")


# === Синхронные обёртки для Celery ===


def _run_async(coro):
    """Запустить корутину в синхронном контексте"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(coro)
    else:
        # Если уже есть event loop - создаём новый в отдельном потоке
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()


class AsyncR2StorageSync:
    """
    Синхронная обёртка над AsyncR2Storage для использования в Celery.
    Использует aioboto3 под капотом, но предоставляет sync API.
    """

    def __init__(self, **kwargs):
        self._async_storage = AsyncR2Storage(**kwargs)

    @property
    def bucket_name(self) -> str:
        return self._async_storage.bucket_name

    def download_file(self, remote_key: str, local_path: str) -> bool:
        return _run_async(self._async_storage.download_file(remote_key, local_path))

    def upload_file(
        self, local_path: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        return _run_async(
            self._async_storage.upload_file(local_path, remote_key, content_type)
        )

    def download_text(self, remote_key: str) -> Optional[str]:
        return _run_async(self._async_storage.download_text(remote_key))

    def upload_text(
        self, content: str, remote_key: str, content_type: Optional[str] = None
    ) -> bool:
        return _run_async(
            self._async_storage.upload_text(content, remote_key, content_type)
        )

    def exists(self, remote_key: str) -> bool:
        return _run_async(self._async_storage.exists(remote_key))

    def delete_object(self, remote_key: str) -> bool:
        return _run_async(self._async_storage.delete_object(remote_key))

    def list_objects(self, prefix: str = "") -> List[str]:
        return _run_async(self._async_storage.list_objects(prefix))

    def generate_presigned_url(
        self, remote_key: str, expiration: int = 3600
    ) -> Optional[str]:
        # presigned URL генерируется синхронно через boto3 (не требует network)
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=self._async_storage.endpoint_url,
            aws_access_key_id=self._async_storage.access_key_id,
            aws_secret_access_key=self._async_storage.secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        try:
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": remote_key},
                ExpiresIn=expiration,
            )
        except Exception as e:
            logger.error(f"Presigned URL error: {e}")
            return None
