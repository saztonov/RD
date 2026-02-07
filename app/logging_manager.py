"""
Динамический менеджер логирования клиентского приложения.

Позволяет переключать папку логов в runtime:
- При открытии PDF - логи пишутся в папку PDF файла
- При закрытии PDF - логи возвращаются в папку проектов или дефолтную
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Настройки логирования
LOG_FILENAME = "client.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class DynamicRotatingFileHandler(RotatingFileHandler):
    """
    RotatingFileHandler с поддержкой динамического переключения файла.

    Позволяет менять путь к файлу логов в runtime без пересоздания handler'а.
    """

    def switch_file(self, new_path: Path) -> bool:
        """
        Переключить логирование на новый файл.

        Args:
            new_path: Путь к новому файлу логов

        Returns:
            True если переключение успешно
        """
        try:
            # Закрыть текущий stream
            if self.stream:
                self.stream.flush()
                self.stream.close()
                self.stream = None

            # Создать директорию если нужно
            new_path.parent.mkdir(parents=True, exist_ok=True)

            # Обновить путь
            self.baseFilename = str(new_path)

            # Открыть новый файл
            self.stream = self._open()

            return True
        except Exception as e:
            # При ошибке пытаемся восстановить логирование в stdout
            sys.stderr.write(f"Error switching log file: {e}\n")
            return False


class LoggingManager:
    """
    Singleton менеджер логирования с поддержкой динамической смены папки.

    Использование:
        manager = get_logging_manager()
        manager.setup(log_level=logging.INFO)

        # При открытии PDF
        manager.switch_to_pdf_folder("/path/to/document.pdf")

        # При закрытии PDF
        manager.switch_to_projects_folder()
    """

    _instance: Optional["LoggingManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self._file_handler: Optional[DynamicRotatingFileHandler] = None
        self._console_handler: Optional[logging.StreamHandler] = None
        self._current_log_path: Optional[Path] = None
        self._default_log_dir = Path("logs")
        self._log_level = logging.INFO

    def setup(self, log_level: int = logging.INFO):
        """
        Инициализировать систему логирования.

        Args:
            log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
        """
        self._log_level = log_level

        # Создаём форматтер
        formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

        # Настраиваем корневой логгер
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

        # Удаляем существующие handlers
        root_logger.handlers.clear()

        # Console handler
        self._console_handler = logging.StreamHandler(sys.stdout)
        self._console_handler.setLevel(log_level)
        self._console_handler.setFormatter(formatter)
        root_logger.addHandler(self._console_handler)

        # File handler - начинаем с дефолтной папки
        self._default_log_dir.mkdir(exist_ok=True)
        default_log_path = self._default_log_dir / LOG_FILENAME

        self._file_handler = DynamicRotatingFileHandler(
            str(default_log_path),
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8"
        )
        self._file_handler.setLevel(log_level)
        self._file_handler.setFormatter(formatter)
        root_logger.addHandler(self._file_handler)

        self._current_log_path = default_log_path

        # Подавить шум от внешних библиотек
        self._configure_library_loggers()

        # Логируем запуск
        logger = logging.getLogger(__name__)
        logger.info("=" * 60)
        logger.info("PDF Annotation Tool - запуск приложения")
        logger.info(f"Уровень логирования: {logging.getLevelName(log_level)}")
        logger.info(f"Файл логов: {default_log_path}")
        logger.info("=" * 60)

    def switch_to_pdf_folder(self, pdf_path: str):
        """
        Переключить логи в папку PDF файла.

        Args:
            pdf_path: Путь к PDF файлу
        """
        if not pdf_path:
            return

        pdf_dir = Path(pdf_path).parent
        new_log_path = pdf_dir / LOG_FILENAME

        self._switch_log_file(new_log_path)

    def switch_to_projects_folder(self):
        """
        Переключить логи в папку проектов (fallback на дефолтную).
        """
        from app.gui.folder_settings_dialog import get_projects_dir

        projects_dir = get_projects_dir()
        if projects_dir:
            new_log_path = Path(projects_dir) / LOG_FILENAME
            self._switch_log_file(new_log_path)
        else:
            self.switch_to_default()

    def switch_to_default(self):
        """
        Вернуть логи в дефолтную папку (logs/).
        """
        default_log_path = self._default_log_dir / LOG_FILENAME
        self._switch_log_file(default_log_path)

    def _switch_log_file(self, new_path: Path):
        """
        Переключить на новый файл логов.

        Args:
            new_path: Путь к новому файлу логов
        """
        if self._current_log_path == new_path:
            return

        if not self._file_handler:
            return

        logger = logging.getLogger(__name__)
        logger.info(f"Переключение логов: {self._current_log_path} -> {new_path}")

        if self._file_handler.switch_file(new_path):
            self._current_log_path = new_path
            logger.info(f"Логи переключены на: {new_path}")
        else:
            logger.warning(f"Не удалось переключить логи на: {new_path}")

    def _configure_library_loggers(self):
        """
        Настроить уровни логирования для внешних библиотек.

        Подавляет DEBUG/INFO сообщения от шумных библиотек.
        """
        noisy_loggers = [
            "PIL",
            "botocore",
            "boto3",
            "urllib3",
            "httpcore",
            "httpx",
            "s3transfer",
        ]
        for name in noisy_loggers:
            logging.getLogger(name).setLevel(logging.WARNING)

    @property
    def current_log_path(self) -> Optional[Path]:
        """Текущий путь к файлу логов."""
        return self._current_log_path

    @property
    def log_level(self) -> int:
        """Текущий уровень логирования."""
        return self._log_level


def get_logging_manager() -> LoggingManager:
    """
    Получить singleton экземпляр менеджера логирования.

    Returns:
        LoggingManager instance
    """
    return LoggingManager()
