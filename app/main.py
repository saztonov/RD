"""
Точка входа приложения
Запуск GUI приложения
"""

import logging
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv()  # Загрузка .env до импорта остальных модулей

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.logging_manager import get_logging_manager


def main():
    """
    Главная функция - точка входа в приложение
    """
    # Настраиваем логирование через менеджер
    # Для отладки используйте logging.DEBUG
    log_manager = get_logging_manager()
    log_manager.setup(log_level=logging.INFO)

    logger = logging.getLogger(__name__)
    
    # Включить мониторинг производительности через env переменную
    import os
    if os.getenv("ENABLE_PERFORMANCE_MONITOR", "").lower() in ("1", "true", "yes"):
        from app.gui.performance_monitor import enable_performance_monitoring
        enable_performance_monitoring()
        logger.info("🔍 Мониторинг производительности включен")

    try:
        # Создаём приложение Qt
        app = QApplication(sys.argv)

        # Устанавливаем стиль (опционально)
        app.setStyle("Fusion")

        logger.info("Qt приложение инициализировано")

        # Создаём и показываем главное окно
        window = MainWindow()
        window.show()

        logger.info("Главное окно открыто")

        # Запускаем event loop
        exit_code = app.exec()

        logger.info(f"Приложение завершено с кодом: {exit_code}")
        sys.exit(exit_code)

    except Exception as e:
        logger.critical(
            f"Критическая ошибка при запуске приложения: {e}", exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
