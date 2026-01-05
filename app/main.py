"""
Точка входа приложения
Запуск GUI приложения
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # Загрузка .env до импорта остальных модулей

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow


def setup_logging(log_level=logging.DEBUG):
    """
    Настройка логирования приложения

    Args:
        log_level: уровень логирования (DEBUG, INFO, WARNING, ERROR)
    """
    # Создаём директорию для логов
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Формат логов
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Настраиваем корневой логгер
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            # Вывод в файл
            logging.FileHandler(log_dir / "app.log", encoding="utf-8", mode="a"),
            # Вывод в консоль
            logging.StreamHandler(sys.stdout),
        ],
        force=True,  # Принудительная перенастройка
    )

    # Устанавливаем уровни для отдельных модулей
    logging.getLogger("app.pdf_utils").setLevel(log_level)
    logging.getLogger("app.ocr").setLevel(log_level)
    logging.getLogger("app.gui.main_window").setLevel(log_level)

    # Отключаем DEBUG сообщения от сторонних библиотек
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.INFO)

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("PDF Annotation Tool - запуск приложения")
    logger.info(f"Уровень логирования: {logging.getLevelName(log_level)}")
    logger.info("=" * 60)


def main():
    """
    Главная функция - точка входа в приложение
    """
    # Настраиваем логирование
    # Для отладки используйте logging.DEBUG
    setup_logging(log_level=logging.INFO)

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
