"""Утилиты для работы с R2"""
import logging
from pathlib import Path
from typing import Optional

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class R2UtilsMixin:
    """Миксин для утилит R2"""
    
    def _guess_content_type(self, file_path: Path) -> str:
        """Определить MIME тип по расширению"""
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
        }

        return content_types.get(extension, "application/octet-stream")

    def list_objects(self, prefix: str = "") -> list[str]:
        """
        Список объектов в bucket

        Args:
            prefix: Префикс для фильтрации

        Returns:
            Список ключей объектов
        """
        try:
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)

            if "Contents" not in response:
                return []

            return [obj["Key"] for obj in response["Contents"]]

        except ClientError as e:
            logger.error(f"Ошибка получения списка объектов: {e}")
            return []

    def delete_object(self, remote_key: str) -> bool:
        """
        Удалить объект из R2

        Args:
            remote_key: Ключ объекта

        Returns:
            True если успешно
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=remote_key)
            logger.info(f"✅ Объект удален из R2: {remote_key}")
            return True

        except ClientError as e:
            logger.error(f"❌ Ошибка удаления объекта: {e}")
            return False

    def rename_object(self, old_key: str, new_key: str) -> bool:
        """
        Переименовать объект в R2 (копирование + удаление)

        Args:
            old_key: Старый ключ объекта
            new_key: Новый ключ объекта

        Returns:
            True если успешно
        """
        try:
            # Копируем объект с новым ключом
            copy_source = {"Bucket": self.bucket_name, "Key": old_key}
            self.s3_client.copy_object(
                Bucket=self.bucket_name,
                CopySource=copy_source,
                Key=new_key
            )
            logger.info(f"✅ Объект скопирован: {old_key} → {new_key}")
            
            # Удаляем старый объект
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=old_key)
            logger.info(f"✅ Старый объект удален: {old_key}")
            
            return True

        except ClientError as e:
            logger.error(f"❌ Ошибка переименования объекта: {e}")
            return False

    def generate_presigned_url(self, remote_key: str, expiration: int = 3600) -> Optional[str]:
        """
        Создать временную ссылку на объект

        Args:
            remote_key: Ключ объекта
            expiration: Время жизни ссылки в секундах

        Returns:
            URL или None при ошибке
        """
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket_name, "Key": remote_key}, ExpiresIn=expiration
            )
            return url

        except ClientError as e:
            logger.error(f"Ошибка генерации presigned URL: {e}")
            return None

    def list_by_prefix(self, prefix: str) -> list[str]:
        """
        Получить список ключей с определенным префиксом

        Args:
            prefix: Префикс для поиска

        Returns:
            Список ключей
        """
        try:
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)

            if "Contents" not in response:
                return []

            return [obj["Key"] for obj in response["Contents"]]
        except ClientError as e:
            logger.error(f"❌ Ошибка получения списка из R2: {e}")
            return []

    # Алиас для совместимости
    list_files = list_by_prefix

    def delete_by_prefix(self, prefix: str) -> int:
        """
        Удалить все объекты с заданным префиксом

        Args:
            prefix: Префикс для удаления

        Returns:
            Количество удалённых объектов
        """
        keys = self.list_by_prefix(prefix)
        if not keys:
            return 0

        deleted = 0
        for key in keys:
            if self.delete_object(key):
                deleted += 1
        
        logger.info(f"✅ Удалено {deleted}/{len(keys)} объектов по префиксу: {prefix}")
        return deleted

    def list_objects_with_metadata(self, prefix: str) -> list[dict]:
        """
        Получить список объектов с метаданными (LastModified, Size, ETag)

        Args:
            prefix: Префикс для поиска

        Returns:
            Список dict с ключами: Key, LastModified, Size, ETag
        """
        try:
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)

            if "Contents" not in response:
                return []

            return [
                {
                    "Key": obj["Key"],
                    "LastModified": obj.get("LastModified"),
                    "Size": obj.get("Size", 0),
                    "ETag": obj.get("ETag", "").strip('"'),
                }
                for obj in response["Contents"]
            ]
        except ClientError as e:
            logger.error(f"❌ Ошибка получения списка из R2: {e}")
            return []

    def get_object_metadata(self, remote_key: str) -> Optional[dict]:
        """
        Получить метаданные объекта (Size, ETag)

        Args:
            remote_key: Ключ объекта

        Returns:
            Dict с Size и ETag или None
        """
        try:
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=remote_key)
            return {
                "Size": response.get("ContentLength", 0),
                "ETag": response.get("ETag", "").strip('"'),
            }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return None
            logger.error(f"❌ Ошибка получения метаданных объекта: {e}")
            return None

    def exists(self, remote_key: str) -> bool:
        """
        Проверить существование объекта в R2

        Args:
            remote_key: Ключ объекта

        Returns:
            True если объект существует
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=remote_key)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return False
            logger.error(f"❌ Ошибка проверки существования объекта: {e}")
            return False


