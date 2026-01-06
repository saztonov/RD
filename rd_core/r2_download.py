"""Операции скачивания из R2"""
import logging
import shutil
from pathlib import Path
from typing import Optional

from rd_core.r2_disk_cache import get_disk_cache
from rd_core.r2_errors import handle_r2_download_error

logger = logging.getLogger(__name__)


class R2DownloadMixin:
    """Миксин для операций скачивания из R2"""

    def download_file(
        self, remote_key: str, local_path: str, use_cache: bool = True
    ) -> bool:
        """
        Скачать файл из R2

        Args:
            remote_key: Ключ объекта в R2
            local_path: Локальный путь для сохранения
            use_cache: Использовать дисковый кэш (по умолчанию True)

        Returns:
            True если успешно, False при ошибке
        """
        try:
            local_file = Path(local_path)
            local_file.parent.mkdir(parents=True, exist_ok=True)

            # Проверяем дисковый кэш
            if use_cache:
                disk_cache = get_disk_cache()
                cached_path = disk_cache.get(remote_key)
                if cached_path and cached_path.exists():
                    # Копируем из кэша
                    shutil.copy2(cached_path, local_file)
                    logger.debug(f"R2 cache hit: {remote_key}")
                    return True

            logger.debug(f"Скачивание файла из R2: {remote_key} → {local_path}")

            self.s3_client.download_file(
                self.bucket_name,
                remote_key,
                str(local_file),
                Config=self.transfer_config,
            )

            logger.info(f"✅ Файл скачан из R2: {remote_key}")

            # Добавляем в дисковый кэш
            if use_cache:
                disk_cache = get_disk_cache()
                disk_cache.put(remote_key, local_file)

            return True

        except Exception as e:
            handle_r2_download_error(e, remote_key, "download_file")
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
        except Exception as e:
            handle_r2_download_error(e, remote_key, "download_text")
            return None
