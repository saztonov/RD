"""Операции загрузки в R2"""
import logging
from pathlib import Path
from typing import Optional

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class R2UploadMixin:
    """Миксин для операций загрузки в R2"""

    def upload_file(
        self, local_path: str, remote_key: str, content_type: Optional[str] = None
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
            logger.debug(
                f"Попытка загрузки файла: {local_file} → {self.bucket_name}/{remote_key}"
            )

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
                extra_args["ContentType"] = content_type

            logger.debug(f"Начало загрузки в bucket '{self.bucket_name}'...")

            self.s3_client.upload_file(
                str(local_file),
                self.bucket_name,
                remote_key,
                ExtraArgs=extra_args,
                Config=self.transfer_config,
            )

            logger.info(f"✅ Файл загружен в R2: {remote_key} ({file_size} байт)")
            return True

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            
            # Проверяем сетевые ошибки
            if error_code in ["RequestTimeout", "ServiceUnavailable"]:
                logger.warning(f"⚠️ Сетевая ошибка при загрузке в R2: {error_msg}")
                # Добавляем в очередь отложенной синхронизации
                try:
                    from app.gui.sync_queue import get_sync_queue, SyncOperation, SyncOperationType
                    from datetime import datetime
                    import uuid
                    
                    queue = get_sync_queue()
                    op = SyncOperation(
                        id=str(uuid.uuid4()),
                        type=SyncOperationType.UPLOAD_FILE,
                        timestamp=datetime.now().isoformat(),
                        local_path=local_path,
                        r2_key=remote_key,
                        data={"content_type": content_type}
                    )
                    queue.add_operation(op)
                    logger.info(f"Файл добавлен в очередь синхронизации: {remote_key}")
                except Exception as queue_error:
                    logger.error(f"Не удалось добавить в очередь: {queue_error}")
                return False
            
            logger.error(f"❌ ClientError при загрузке в R2: {error_code} - {error_msg}")
            logger.error(f"   Bucket: {self.bucket_name}, Key: {remote_key}")
            logger.error(f"   Response: {e.response}", exc_info=True)
            return False
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"⚠️ Сетевая ошибка при загрузке в R2: {e}")
            # Добавляем в очередь отложенной синхронизации
            try:
                from app.gui.sync_queue import get_sync_queue, SyncOperation, SyncOperationType
                from datetime import datetime
                import uuid
                
                queue = get_sync_queue()
                op = SyncOperation(
                    id=str(uuid.uuid4()),
                    type=SyncOperationType.UPLOAD_FILE,
                    timestamp=datetime.now().isoformat(),
                    local_path=local_path,
                    r2_key=remote_key,
                    data={"content_type": content_type}
                )
                queue.add_operation(op)
                logger.info(f"Файл добавлен в очередь синхронизации: {remote_key}")
            except Exception as queue_error:
                logger.error(f"Не удалось добавить в очередь: {queue_error}")
            return False
        except Exception as e:
            logger.error(
                f"❌ Неожиданная ошибка загрузки в R2: {type(e).__name__}: {e}",
                exc_info=True,
            )
            logger.error(f"   Файл: {local_path}")
            logger.error(f"   Bucket: {self.bucket_name}, Key: {remote_key}")
            return False

    def upload_directory(
        self, local_dir: str, remote_prefix: str = "", recursive: bool = True
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
        logger.info("=== Начало загрузки директории в R2 ===")
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
            remote_key = (
                f"{remote_prefix}/{relative_path.as_posix()}"
                if remote_prefix
                else relative_path.as_posix()
            )

            logger.info(f"[{idx}/{len(files)}] Загрузка: {relative_path.as_posix()}")

            if self.upload_file(str(file_path), remote_key):
                success_count += 1
            else:
                error_count += 1

        logger.info(
            f"=== Загрузка завершена: ✅ {success_count} успешно, ❌ {error_count} ошибок ==="
        )
        return (success_count, error_count)

    def upload_text(
        self, content: str, remote_key: str, content_type: str = None
    ) -> bool:
        """
        Загрузить текстовый контент в R2

        Args:
            content: Текстовое содержимое
            remote_key: Ключ объекта в R2
            content_type: MIME тип (auto для JSON по расширению)

        Returns:
            True если успешно
        """
        try:
            # Автоопределение content-type для JSON
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
            logger.info(f"✅ Текст загружен в R2: {remote_key}")
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            
            # Проверяем сетевые ошибки
            if error_code in ["RequestTimeout", "ServiceUnavailable"]:
                logger.warning(f"⚠️ Сетевая ошибка при загрузке текста в R2")
                # Сохраняем текст во временный файл и добавляем в очередь
                try:
                    from app.gui.sync_queue import get_sync_queue, SyncOperation, SyncOperationType
                    from datetime import datetime
                    import uuid
                    import tempfile
                    from pathlib import Path
                    
                    # Создаём временный файл
                    temp_file = Path(tempfile.gettempdir()) / "RD" / "sync_pending" / f"{uuid.uuid4()}.txt"
                    temp_file.parent.mkdir(parents=True, exist_ok=True)
                    temp_file.write_text(content, encoding='utf-8')
                    
                    queue = get_sync_queue()
                    op = SyncOperation(
                        id=str(uuid.uuid4()),
                        type=SyncOperationType.UPLOAD_FILE,
                        timestamp=datetime.now().isoformat(),
                        local_path=str(temp_file),
                        r2_key=remote_key,
                        data={"content_type": content_type, "is_temp": True}
                    )
                    queue.add_operation(op)
                    logger.info(f"Текст добавлен в очередь синхронизации: {remote_key}")
                except Exception as queue_error:
                    logger.error(f"Не удалось добавить в очередь: {queue_error}")
                return False
            
            logger.error(f"❌ Ошибка загрузки текста в R2: {e}")
            return False
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"⚠️ Сетевая ошибка при загрузке текста в R2: {e}")
            # Сохраняем текст во временный файл и добавляем в очередь
            try:
                from app.gui.sync_queue import get_sync_queue, SyncOperation, SyncOperationType
                from datetime import datetime
                import uuid
                import tempfile
                from pathlib import Path
                
                temp_file = Path(tempfile.gettempdir()) / "RD" / "sync_pending" / f"{uuid.uuid4()}.txt"
                temp_file.parent.mkdir(parents=True, exist_ok=True)
                temp_file.write_text(content, encoding='utf-8')
                
                queue = get_sync_queue()
                op = SyncOperation(
                    id=str(uuid.uuid4()),
                    type=SyncOperationType.UPLOAD_FILE,
                    timestamp=datetime.now().isoformat(),
                    local_path=str(temp_file),
                    r2_key=remote_key,
                    data={"content_type": content_type, "is_temp": True}
                )
                queue.add_operation(op)
                logger.info(f"Текст добавлен в очередь синхронизации: {remote_key}")
            except Exception as queue_error:
                logger.error(f"Не удалось добавить в очередь: {queue_error}")
            return False
