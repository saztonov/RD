#!/usr/bin/env python3
"""
Скрипт для создания/обновления промптов в R2 Storage (rd1/prompts/)
Промпты создаются с дефолтными значениями или из локальных файлов
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


# Дефолтные промпты для типов блоков
DEFAULT_PROMPTS = {
    "text": """Распознай текст с изображения.
Сохрани структуру и форматирование.
Выведи только распознанный текст без комментариев.""",
    
    "table": """Распознай таблицу с изображения.
Выведи таблицу в формате Markdown.
Сохрани все колонки и строки.
Если данные неразборчивы - пометь как [нечитаемо].""",
    
    "image": """Опиши изображение.
Укажи:
- Тип изображения (схема, чертеж, фото, график)
- Основные элементы
- Текст на изображении если есть
Формат: структурированное описание.""",
}

# Стандартные категории
DEFAULT_CATEGORIES = ["Текст", "Таблица", "Картинка"]

# Маппинг категорий на типы блоков (для промптов)
CATEGORY_TO_TYPE = {
    "Текст": "text",
    "Таблица": "table",
    "Картинка": "image",
}


def upload_prompts_to_r2():
    """Создать промпты в R2 Storage (rd1/prompts/)"""
    
    try:
        logger.info("Инициализация R2 Storage...")
        r2 = R2Storage()
        logger.info("✅ R2 Storage подключен")
        
        success_count = 0
        error_count = 0
        
        # 1. Загружаем базовые промпты для типов блоков
        logger.info("\n=== Загрузка промптов типов блоков ===")
        prompts_dir = project_root / "prompts"
        
        for prompt_name, default_content in DEFAULT_PROMPTS.items():
            # Пробуем загрузить из локального файла, иначе используем дефолт
            local_file = prompts_dir / f"{prompt_name}.txt"
            ocr_local_file = prompts_dir / f"ocr_{prompt_name}.txt"
            
            if local_file.exists():
                content = local_file.read_text(encoding='utf-8')
                logger.info(f"  📁 {prompt_name}.txt (из локального файла)")
            elif ocr_local_file.exists():
                content = ocr_local_file.read_text(encoding='utf-8')
                logger.info(f"  📁 {prompt_name}.txt (из ocr_{prompt_name}.txt)")
            else:
                content = default_content
                logger.info(f"  📝 {prompt_name}.txt (дефолтный)")
            
            remote_key = f"prompts/{prompt_name}.txt"
            if r2.upload_text(content, remote_key):
                logger.info(f"    ✅ Загружено: {remote_key}")
                success_count += 1
            else:
                logger.error(f"    ❌ Ошибка: {remote_key}")
                error_count += 1
        
        # 2. Создаем список категорий
        logger.info("\n=== Создание списка категорий ===")
        categories_content = "\n".join(DEFAULT_CATEGORIES)
        if r2.upload_text(categories_content, "prompts/categories_list.txt"):
            logger.info(f"  ✅ categories_list.txt ({len(DEFAULT_CATEGORIES)} категорий)")
            success_count += 1
        else:
            logger.error(f"  ❌ categories_list.txt")
            error_count += 1
        
        # 3. Создаем промпты для категорий
        logger.info("\n=== Загрузка промптов категорий ===")
        for category, block_type in CATEGORY_TO_TYPE.items():
            prompt_name = f"category_{category}"
            
            # Используем тот же контент что и для типа блока
            local_file = prompts_dir / f"{block_type}.txt"
            ocr_local_file = prompts_dir / f"ocr_{block_type}.txt"
            
            if local_file.exists():
                content = local_file.read_text(encoding='utf-8')
            elif ocr_local_file.exists():
                content = ocr_local_file.read_text(encoding='utf-8')
            else:
                content = DEFAULT_PROMPTS.get(block_type, f"Промт для {category}")
            
            remote_key = f"prompts/{prompt_name}.txt"
            if r2.upload_text(content, remote_key):
                logger.info(f"  ✅ {prompt_name}.txt")
                success_count += 1
            else:
                logger.error(f"  ❌ {prompt_name}.txt")
                error_count += 1
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Завершено: ✅ {success_count} успешно, ❌ {error_count} ошибок")
        logger.info(f"{'='*60}")
        logger.info(f"\nПромпты сохранены в R2 bucket 'rd1' в папке 'prompts/'")
        
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





