"""
Cloudflare R2 Object Storage интеграция
Загрузка результатов OCR в S3-совместимое хранилище
"""

import logging
import os
from pathlib import Path
from typing import Optional
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()


class R2Storage:
    """Клиент для работы с Cloudflare R2 Object Storage"""
    
    def __init__(
        self,
        account_id: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None
    ):
        """
        Инициализация R2 клиента
        
        Args:
            account_id: Cloudflare Account ID
            access_key_id: R2 Access Key ID
            secret_access_key: R2 Secret Access Key
            bucket_name: Имя bucket (по умолчанию 'rd1')
            endpoint_url: R2 endpoint URL
        """
        logger.info("=== Инициализация R2Storage ===")
        
        # Загружаем из .env если не указано явно
        self.account_id = account_id or os.getenv("R2_ACCOUNT_ID")
        self.access_key_id = access_key_id or os.getenv("R2_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = bucket_name or os.getenv("R2_BUCKET_NAME", "rd1")
        
        logger.info(f"R2_ACCOUNT_ID: {'✓' if self.account_id else '✗ НЕ УКАЗАН'}")
        logger.info(f"R2_ACCESS_KEY_ID: {'✓' if self.access_key_id else '✗ НЕ УКАЗАН'}")
        logger.info(f"R2_SECRET_ACCESS_KEY: {'✓' if self.secret_access_key else '✗ НЕ УКАЗАН'}")
        logger.info(f"R2_BUCKET_NAME: {self.bucket_name}")
        
        # Формируем endpoint URL
        if endpoint_url:
            self.endpoint_url = endpoint_url
        elif self.account_id:
            self.endpoint_url = f"https://{self.account_id}.r2.cloudflarestorage.com"
        else:
            self.endpoint_url = os.getenv("R2_ENDPOINT_URL")
        
        logger.info(f"R2_ENDPOINT_URL: {self.endpoint_url}")
        
        # Проверка обязательных параметров
        if not all([self.access_key_id, self.secret_access_key, self.endpoint_url]):
            error_msg = (
                "Не указаны обязательные параметры R2. "
                "Проверьте .env файл: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID"
            )
            logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)
        
        # Создаем S3 клиент для R2 с настройками retry и timeouts
        try:
            # Конфигурация для стабильной работы с R2
            client_config = Config(
                retries={
                    'max_attempts': 10,
                    'mode': 'adaptive'  # Адаптивные retry с backoff
                },
                connect_timeout=30,
                read_timeout=120,
                max_pool_connections=10
            )
            
            # Настройки multipart upload - оптимизированы для скорости
            self.transfer_config = TransferConfig(
                multipart_threshold=100 * 1024 * 1024,  # 100MB - только для очень больших файлов
                max_concurrency=20,  # Больше параллельных соединений
                multipart_chunksize=50 * 1024 * 1024,  # 50MB chunks
                use_threads=True
            )
            
            self.s3_client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name='auto',  # R2 использует 'auto'
                config=client_config
            )
            logger.info(f"✅ R2Storage инициализирован (bucket: {self.bucket_name}, endpoint: {self.endpoint_url})")
        except Exception as e:
            logger.error(f"❌ Ошибка создания S3 клиента: {e}", exc_info=True)
            raise
    
    def upload_file(
        self,
        local_path: str,
        remote_key: str,
        content_type: Optional[str] = None
    ) -> bool:
        """
        Загрузить файл в R2
        
        Args:
            local_path: Локальный путь к файлу
            remote_key: Ключ объекта в R2 (путь в bucket)
            content_type: MIME тип (определяется автоматически если None)
        
        Returns:
            True если успешно, False при ошибке
        """
        try:
            local_file = Path(local_path)
            logger.debug(f"Попытка загрузки файла: {local_file} → {self.bucket_name}/{remote_key}")
            
            if not local_file.exists():
                logger.error(f"❌ Файл не найден: {local_path}")
                return False
            
            file_size = local_file.stat().st_size
            logger.debug(f"Размер файла: {file_size} байт")
            
            # Определяем content_type если не указан
            if content_type is None:
                content_type = self._guess_content_type(local_file)
            
            logger.debug(f"Content-Type: {content_type}")
            
            # Загружаем файл
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type
            
            logger.debug(f"Начало загрузки в bucket '{self.bucket_name}'...")
            
            self.s3_client.upload_file(
                str(local_file),
                self.bucket_name,
                remote_key,
                ExtraArgs=extra_args,
                Config=self.transfer_config
            )
            
            logger.info(f"✅ Файл загружен в R2: {remote_key} ({file_size} байт)")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"❌ ClientError при загрузке в R2: {error_code} - {error_msg}")
            logger.error(f"   Bucket: {self.bucket_name}, Key: {remote_key}")
            logger.error(f"   Response: {e.response}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка загрузки в R2: {type(e).__name__}: {e}", exc_info=True)
            logger.error(f"   Файл: {local_path}")
            logger.error(f"   Bucket: {self.bucket_name}, Key: {remote_key}")
            return False
    
    def upload_directory(
        self,
        local_dir: str,
        remote_prefix: str = "",
        recursive: bool = True
    ) -> tuple[int, int]:
        """
        Загрузить директорию в R2
        
        Args:
            local_dir: Локальная директория
            remote_prefix: Префикс для объектов в R2
            recursive: Рекурсивная загрузка поддиректорий
        
        Returns:
            (успешно загружено, ошибок)
        """
        logger.info(f"=== Начало загрузки директории в R2 ===")
        logger.info(f"Локальная директория: {local_dir}")
        logger.info(f"Remote prefix: {remote_prefix}")
        logger.info(f"Recursive: {recursive}")
        
        local_path = Path(local_dir)
        if not local_path.is_dir():
            logger.error(f"❌ Директория не найдена: {local_dir}")
            return (0, 1)
        
        success_count = 0
        error_count = 0
        
        # Получаем список файлов
        if recursive:
            files = list(local_path.rglob("*"))
        else:
            files = list(local_path.glob("*"))
        
        files = [f for f in files if f.is_file()]
        
        logger.info(f"Найдено файлов для загрузки: {len(files)}")
        
        for idx, file_path in enumerate(files, 1):
            # Формируем remote_key с сохранением структуры
            relative_path = file_path.relative_to(local_path)
            remote_key = f"{remote_prefix}/{relative_path.as_posix()}" if remote_prefix else relative_path.as_posix()
            
            logger.info(f"[{idx}/{len(files)}] Загрузка: {relative_path.as_posix()}")
            
            if self.upload_file(str(file_path), remote_key):
                success_count += 1
            else:
                error_count += 1
        
        logger.info(f"=== Загрузка завершена: ✅ {success_count} успешно, ❌ {error_count} ошибок ===")
        return (success_count, error_count)
    
    def upload_ocr_results(
        self,
        output_dir: str,
        project_name: Optional[str] = None
    ) -> bool:
        """
        Загрузить результаты OCR в R2
        
        Args:
            output_dir: Директория с результатами OCR
            project_name: Имя проекта (используется как префикс)
        
        Returns:
            True если успешно
        """
        logger.info("=" * 60)
        logger.info("=== ЗАГРУЗКА РЕЗУЛЬТАТОВ OCR В R2 ===")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Project name: {project_name}")
        
        output_path = Path(output_dir)
        if not output_path.exists():
            logger.error(f"❌ Директория результатов не найдена: {output_dir}")
            return False
        
        # Формируем префикс
        if project_name:
            remote_prefix = f"ocr_results/{project_name}"
        else:
            remote_prefix = f"ocr_results/{output_path.name}"
        
        logger.info(f"Remote prefix в R2: {remote_prefix}")
        logger.info(f"Bucket: {self.bucket_name}")
        
        success, errors = self.upload_directory(str(output_path), remote_prefix)
        
        if errors == 0:
            logger.info(f"✅ Все файлы успешно загружены в R2 bucket '{self.bucket_name}'")
            return True
        else:
            logger.warning(f"⚠️ Загрузка завершена с ошибками: {success} успешно, {errors} ошибок")
            return False
    
    def _guess_content_type(self, file_path: Path) -> str:
        """Определить MIME тип по расширению"""
        extension = file_path.suffix.lower()
        
        content_types = {
            '.pdf': 'application/pdf',
            '.json': 'application/json',
            '.md': 'text/markdown',
            '.txt': 'text/plain',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
        }
        
        return content_types.get(extension, 'application/octet-stream')
    
    def list_objects(self, prefix: str = "") -> list[str]:
        """
        Список объектов в bucket
        
        Args:
            prefix: Префикс для фильтрации
        
        Returns:
            Список ключей объектов
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            if 'Contents' not in response:
                return []
            
            return [obj['Key'] for obj in response['Contents']]
            
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
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=remote_key
            )
            logger.info(f"✅ Объект удален из R2: {remote_key}")
            return True
            
        except ClientError as e:
            logger.error(f"❌ Ошибка удаления объекта: {e}")
            return False
    
    def generate_presigned_url(
        self,
        remote_key: str,
        expiration: int = 3600
    ) -> Optional[str]:
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
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': remote_key
                },
                ExpiresIn=expiration
            )
            return url
            
        except ClientError as e:
            logger.error(f"Ошибка генерации presigned URL: {e}")
            return None
    
    def upload_text(
        self,
        content: str,
        remote_key: str
    ) -> bool:
        """
        Загрузить текстовый контент в R2
        
        Args:
            content: Текстовое содержимое
            remote_key: Ключ объекта в R2
        
        Returns:
            True если успешно
        """
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=remote_key,
                Body=content.encode('utf-8'),
                ContentType='text/plain; charset=utf-8'
            )
            logger.info(f"✅ Текст загружен в R2: {remote_key}")
            return True
        except ClientError as e:
            logger.error(f"❌ Ошибка загрузки текста в R2: {e}")
            return False
    
    def download_text(
        self,
        remote_key: str
    ) -> Optional[str]:
        """
        Скачать текстовый контент из R2
        
        Args:
            remote_key: Ключ объекта
        
        Returns:
            Текст или None при ошибке
        """
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=remote_key
            )
            content = response['Body'].read().decode('utf-8')
            logger.info(f"✅ Текст загружен из R2: {remote_key}")
            return content
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                logger.warning(f"⚠️ Файл не найден в R2: {remote_key}")
            else:
                logger.error(f"❌ Ошибка загрузки текста из R2: {e}")
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
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            if 'Contents' not in response:
                return []
            
            return [obj['Key'] for obj in response['Contents']]
        except ClientError as e:
            logger.error(f"❌ Ошибка получения списка из R2: {e}")
            return []
    
    def list_objects_with_metadata(self, prefix: str) -> list[dict]:
        """
        Получить список объектов с метаданными (LastModified, Size)
        
        Args:
            prefix: Префикс для поиска
        
        Returns:
            Список dict с ключами: Key, LastModified, Size
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            if 'Contents' not in response:
                return []
            
            return [
                {
                    'Key': obj['Key'],
                    'LastModified': obj.get('LastModified'),
                    'Size': obj.get('Size', 0)
                }
                for obj in response['Contents']
            ]
        except ClientError as e:
            logger.error(f"❌ Ошибка получения списка из R2: {e}")
            return []


def upload_ocr_to_r2(output_dir: str, project_name: Optional[str] = None) -> bool:
    """
    Вспомогательная функция для загрузки результатов OCR в R2
    
    Args:
        output_dir: Директория с результатами
        project_name: Имя проекта
    
    Returns:
        True если успешно
    """
    logger.info("=" * 60)
    logger.info("=== ВЫЗОВ upload_ocr_to_r2() ===")
    logger.info(f"output_dir: {output_dir}")
    logger.info(f"project_name: {project_name}")
    
    try:
        logger.info("Создание экземпляра R2Storage...")
        r2 = R2Storage()
        
        logger.info("Вызов r2.upload_ocr_results()...")
        result = r2.upload_ocr_results(output_dir, project_name)
        
        logger.info(f"Результат: {'✅ SUCCESS' if result else '❌ FAILED'}")
        return result
        
    except ValueError as e:
        logger.error(f"❌ Ошибка инициализации R2 (проверьте .env): {e}")
        logger.error(f"   Убедитесь что в .env указаны: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
        return False
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка загрузки в R2: {type(e).__name__}: {e}", exc_info=True)
        return False

