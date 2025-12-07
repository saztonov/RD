#!/usr/bin/env python3
"""
Скрипт для загрузки стандартных промптов из папки prompts/ в R2 Storage
"""

import sys
from pathlib import Path

# Добавляем корневую папку проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.r2_storage import R2Storage
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def upload_prompts_to_r2():
    """Загрузить все промпты из папки prompts/ в R2"""
    
    try:
        # Инициализация R2
        logger.info("Инициализация R2 Storage...")
        r2 = R2Storage()
        logger.info("✅ R2 Storage подключен")
        
        # Папка с промптами
        prompts_dir = project_root / "prompts"
        if not prompts_dir.exists():
            logger.error(f"❌ Папка не найдена: {prompts_dir}")
            return False
        
        # Загружаем все .txt файлы
        prompt_files = list(prompts_dir.glob("*.txt"))
        logger.info(f"Найдено {len(prompt_files)} промптов")
        
        success_count = 0
        error_count = 0
        
        for prompt_file in prompt_files:
            try:
                # Читаем содержимое
                content = prompt_file.read_text(encoding='utf-8')
                
                # Формируем ключ в R2: prompts/имя_файла.txt
                remote_key = f"prompts/{prompt_file.name}"
                
                # Загружаем
                logger.info(f"Загрузка: {prompt_file.name} → {remote_key}")
                result = r2.upload_text(content, remote_key)
                
                if result:
                    success_count += 1
                    logger.info(f"  ✅ {prompt_file.name}")
                else:
                    error_count += 1
                    logger.error(f"  ❌ {prompt_file.name}")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"  ❌ Ошибка загрузки {prompt_file.name}: {e}")
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Завершено: ✅ {success_count} успешно, ❌ {error_count} ошибок")
        logger.info(f"{'='*60}")
        
        return error_count == 0
        
    except ValueError as e:
        logger.error(f"❌ Ошибка инициализации R2 (проверьте .env): {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = upload_prompts_to_r2()
    sys.exit(0 if success else 1)





