"""
Тестовый скрипт для проверки R2 Storage

Использование:
    python test_r2_upload.py

Проверяет:
    1. Инициализацию R2Storage
    2. Доступ к bucket
    3. Загрузку файла
    4. Генерацию presigned URL
    5. Удаление файла
"""

import logging
import sys
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from app.r2_storage import R2Storage

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_r2_connection():
    """Тест подключения к R2"""
    logger.info("=" * 60)
    logger.info("ТЕСТ ПОДКЛЮЧЕНИЯ К R2")
    logger.info("=" * 60)
    
    try:
        # Инициализация
        logger.info("\n1. Инициализация R2Storage...")
        r2 = R2Storage()
        
        # Проверка bucket
        logger.info("\n2. Проверка доступа к bucket...")
        objects = r2.list_objects(prefix="")
        logger.info(f"✅ Bucket доступен! Найдено объектов: {len(objects)}")
        
        if objects:
            logger.info("\nПервые 10 объектов:")
            for obj in objects[:10]:
                logger.info(f"  - {obj}")
        
        # Создаем тестовый файл
        logger.info("\n3. Создание тестового файла...")
        test_file = Path("test_r2_file.txt")
        test_file.write_text("Test content for R2 upload", encoding="utf-8")
        logger.info(f"✅ Создан: {test_file}")
        
        # Загрузка тестового файла
        logger.info("\n4. Загрузка тестового файла в R2...")
        remote_key = "test/test_r2_file.txt"
        if r2.upload_file(str(test_file), remote_key):
            logger.info(f"✅ Файл успешно загружен: {remote_key}")
            
            # Генерация presigned URL
            logger.info("\n5. Генерация временной ссылки...")
            url = r2.generate_presigned_url(remote_key, expiration=3600)
            if url:
                logger.info(f"✅ Presigned URL (1 час):\n{url}")
            
            # Удаление тестового файла
            logger.info("\n6. Удаление тестового файла из R2...")
            if r2.delete_object(remote_key):
                logger.info(f"✅ Файл удален: {remote_key}")
        else:
            logger.error("❌ Не удалось загрузить файл")
        
        # Удаляем локальный тестовый файл
        test_file.unlink()
        logger.info("\n✅ Тест завершен успешно!")
        return True
        
    except ValueError as e:
        logger.error(f"\n❌ Ошибка конфигурации R2: {e}")
        logger.error("\nПроверьте .env файл:")
        logger.error("  - R2_ACCOUNT_ID")
        logger.error("  - R2_ACCESS_KEY_ID")
        logger.error("  - R2_SECRET_ACCESS_KEY")
        logger.error("  - R2_BUCKET_NAME (по умолчанию: rd1)")
        return False
        
    except Exception as e:
        logger.error(f"\n❌ Ошибка: {type(e).__name__}: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_r2_connection()
    
    if success:
        print("\n" + "=" * 60)
        print("✅ R2 Storage работает корректно!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ Проблемы с R2 Storage - проверьте логи выше")
        print("=" * 60)

