"""Операции скачивания из R2"""
import logging
from pathlib import Path
from typing import Optional

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class R2DownloadMixin:
    """Миксин для операций скачивания из R2"""

    def download_file(self, remote_key: str, local_path: str) -> bool:
        """
        Скачать файл из R2

        Args:
            remote_key: Ключ объекта в R2
            local_path: Локальный путь для сохранения

        Returns:
            True если успешно, False при ошибке
        """
        try:
            local_file = Path(local_path)
            local_file.parent.mkdir(parents=True, exist_ok=True)

            logger.debug(f"Скачивание файла из R2: {remote_key} → {local_path}")

            self.s3_client.download_file(
                self.bucket_name,
                remote_key,
                str(local_file),
                Config=self.transfer_config,
            )

            logger.info(f"✅ Файл скачан из R2: {remote_key}")
            return True

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "NoSuchKey" or error_code == "404":
                logger.warning(f"⚠️ Файл не найден в R2: {remote_key}")
            elif error_code in ["RequestTimeout", "ServiceUnavailable"]:
                logger.warning(f"⚠️ Сетевая ошибка при скачивании из R2: {error_code}")
            else:
                logger.error(f"❌ Ошибка скачивания из R2: {error_code} - {e}")
            return False
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"⚠️ Сетевая ошибка при скачивании из R2: {e}")
            return False
        except Exception as e:
            logger.error(
                f"❌ Неожиданная ошибка скачивания из R2: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return False

    def download_text(self, remote_key: str) -> Optional[str]:
        """
        Скачать текстовый контент из R2

        Args:
            remote_key: Ключ объекта

        Returns:
            Текст или None при ошибке
        """
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name, Key=remote_key
            )
            content = response["Body"].read().decode("utf-8")
            logger.info(f"✅ Текст загружен из R2: {remote_key}")
            return content
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "NoSuchKey":
                logger.warning(f"⚠️ Файл не найден в R2: {remote_key}")
            elif error_code in ["RequestTimeout", "ServiceUnavailable"]:
                logger.warning(f"⚠️ Сетевая ошибка при загрузке текста из R2: {error_code}")
            else:
                logger.error(f"❌ Ошибка загрузки текста из R2: {e}")
            return None
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"⚠️ Сетевая ошибка при загрузке текста из R2: {e}")
            return None
