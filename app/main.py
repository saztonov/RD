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

# Frozen mode: встроенный .env из бандла → рядом с .exe → cwd
if getattr(sys, "frozen", False):
    _meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    _bundled_env = _meipass / ".env"
    _exe_env = Path(sys.executable).parent / ".env"
    if _bundled_env.exists():
        load_dotenv(_bundled_env)
    elif _exe_env.exists():
        load_dotenv(_exe_env)
    else:
        load_dotenv()
else:
    load_dotenv()

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

    import os
    # Endpoint Supabase (может быть reverse proxy — см. docs/SUPABASE_PROXY_SETUP.md)
    logger.info(f"Supabase URL configured: {os.getenv('SUPABASE_URL', '<not set>')}")

    # Включить мониторинг производительности через env переменную
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
