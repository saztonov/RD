"""
R2 Storage клиент для Cloudflare R2 Object Storage

Реализация разбита на миксины:
- r2_upload.py - загрузка файлов
- r2_download.py - скачивание файлов
- r2_utils.py - утилиты (list, delete, rename, exists, etc.)
"""
import logging
import os
import threading

import boto3
from botocore.config import Config

from rd_core.r2_download import R2DownloadMixin
from rd_core.r2_upload import R2UploadMixin
from rd_core.r2_utils import R2UtilsMixin

logger = logging.getLogger(__name__)


class R2Storage(R2UploadMixin, R2DownloadMixin, R2UtilsMixin):
    """
    Синглтон для работы с Cloudflare R2 Object Storage.

    Конфигурация через переменные окружения:
    - R2_ENDPOINT_URL
    - R2_ACCESS_KEY_ID
    - R2_SECRET_ACCESS_KEY
    - R2_BUCKET_NAME
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Инициализация клиента"""
        logger.info("Инициализация R2Storage...")

        # Получаем credentials из ENV
        account_id = os.getenv("R2_ACCOUNT_ID")
        self.endpoint_url = os.getenv("R2_ENDPOINT_URL")

        # Конструируем endpoint_url из account_id если не задан напрямую
        if not self.endpoint_url and account_id:
            self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

        self.access_key = os.getenv("R2_ACCESS_KEY_ID")
        self.secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = os.getenv("R2_BUCKET_NAME")

        if not all(
            [self.endpoint_url, self.access_key, self.secret_key, self.bucket_name]
        ):
            raise ValueError(
                "Не все R2 переменные окружения заданы: "
                "R2_ENDPOINT_URL (или R2_ACCOUNT_ID), R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME"
            )

        logger.info(f"R2 Endpoint: {self.endpoint_url}")
        logger.info(f"R2 Bucket: {self.bucket_name}")

        # Конфигурация с retry
        config = Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=30,
            read_timeout=60,
        )

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=config,
            region_name="auto",
        )

        # Transfer config для multipart upload/download
        # Оптимизировано для массовой параллельной загрузки
        from boto3.s3.transfer import TransferConfig

        self.transfer_config = TransferConfig(
            multipart_threshold=8
            * 1024
            * 1024,  # 8 MB - начинаем multipart для файлов > 8MB
            max_concurrency=20,  # Увеличено для параллельных операций
            multipart_chunksize=8 * 1024 * 1024,  # 8 MB чанки
            use_threads=True,
            max_io_queue=1000,  # Буфер для IO операций
        )

        logger.info("✅ R2Storage инициализирован")

    @classmethod
    def reset_instance(cls):
        """Сбросить синглтон (для тестов)"""
        with cls._lock:
            cls._instance = None
