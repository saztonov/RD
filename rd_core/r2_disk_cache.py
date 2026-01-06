"""Дисковый кэш для файлов из R2 с LRU eviction"""
import hashlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Запись в кэше"""
    path: str  # Путь к файлу в кэше
    r2_key: str  # Оригинальный R2 ключ
    size: int  # Размер файла в байтах
    accessed: float  # Timestamp последнего доступа
    created: float  # Timestamp создания


class R2DiskCache:
    """
    LRU дисковый кэш для файлов из R2.

    Кэширует скачанные файлы локально для повторного использования.
    Автоматически удаляет старые файлы при превышении лимита.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_size_bytes: int = 3_000_000_000,  # 3GB по умолчанию
    ):
        """
        Args:
            cache_dir: Директория для кэша (по умолчанию ~/.rd_cache)
            max_size_bytes: Максимальный размер кэша в байтах
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".rd_cache" / "r2_files"

        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._max_size = max_size_bytes
        self._index_file = self._cache_dir / ".cache_index.json"
        self._index: Dict[str, CacheEntry] = {}
        self._current_size = 0
        self._lock = threading.Lock()

        self._load_index()

    def _load_index(self) -> None:
        """Загрузить индекс кэша с диска"""
        if not self._index_file.exists():
            return

        try:
            with open(self._index_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for r2_key, entry_data in data.get("entries", {}).items():
                entry = CacheEntry(
                    path=entry_data["path"],
                    r2_key=entry_data["r2_key"],
                    size=entry_data["size"],
                    accessed=entry_data["accessed"],
                    created=entry_data["created"],
                )
                # Проверяем что файл существует
                if Path(entry.path).exists():
                    self._index[r2_key] = entry
                    self._current_size += entry.size

            logger.info(
                f"R2DiskCache loaded: {len(self._index)} entries, "
                f"{self._current_size / 1024 / 1024:.1f}MB"
            )
        except Exception as e:
            logger.warning(f"Failed to load cache index: {e}")
            self._index = {}
            self._current_size = 0

    def _save_index(self) -> None:
        """Сохранить индекс кэша на диск"""
        try:
            data = {
                "version": 1,
                "entries": {
                    r2_key: asdict(entry)
                    for r2_key, entry in self._index.items()
                },
            }
            # Атомарная запись через временный файл
            temp_file = self._index_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self._index_file)
        except Exception as e:
            logger.warning(f"Failed to save cache index: {e}")

    def _compute_cache_path(self, r2_key: str) -> Path:
        """Вычислить путь к файлу в кэше на основе R2 ключа"""
        # Используем hash для избежания проблем с длинными путями
        key_hash = hashlib.md5(r2_key.encode()).hexdigest()

        # Сохраняем расширение файла
        ext = Path(r2_key).suffix or ".bin"

        # Создаём структуру директорий для распределения файлов
        # Первые 2 символа хэша как поддиректория
        subdir = key_hash[:2]
        filename = f"{key_hash}{ext}"

        cache_path = self._cache_dir / subdir / filename
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        return cache_path

    def get(self, r2_key: str) -> Optional[Path]:
        """
        Получить путь к файлу из кэша.

        Args:
            r2_key: R2 ключ объекта

        Returns:
            Path к файлу если в кэше, иначе None
        """
        with self._lock:
            entry = self._index.get(r2_key)
            if entry is None:
                return None

            cache_path = Path(entry.path)
            if not cache_path.exists():
                # Файл удалён - чистим запись
                self._current_size -= entry.size
                del self._index[r2_key]
                self._save_index()
                return None

            # Обновляем время доступа (LRU)
            entry.accessed = time.time()
            self._save_index()

            logger.debug(f"R2DiskCache hit: {r2_key}")
            return cache_path

    def put(self, r2_key: str, source_path: Path) -> Optional[Path]:
        """
        Добавить файл в кэш.

        Args:
            r2_key: R2 ключ объекта
            source_path: Путь к исходному файлу

        Returns:
            Path к файлу в кэше, или None при ошибке
        """
        if not source_path.exists():
            return None

        file_size = source_path.stat().st_size

        # Не кэшируем слишком большие файлы (>10% от лимита)
        if file_size > self._max_size * 0.1:
            logger.debug(f"File too large for cache: {r2_key} ({file_size} bytes)")
            return None

        with self._lock:
            # Освобождаем место если нужно
            self._ensure_space(file_size)

            # Вычисляем путь в кэше
            cache_path = self._compute_cache_path(r2_key)

            try:
                # Копируем файл в кэш
                shutil.copy2(source_path, cache_path)

                # Создаём запись
                now = time.time()
                entry = CacheEntry(
                    path=str(cache_path),
                    r2_key=r2_key,
                    size=file_size,
                    accessed=now,
                    created=now,
                )

                # Если файл уже был в кэше - вычитаем старый размер
                if r2_key in self._index:
                    old_entry = self._index[r2_key]
                    self._current_size -= old_entry.size

                self._index[r2_key] = entry
                self._current_size += file_size
                self._save_index()

                logger.debug(
                    f"R2DiskCache put: {r2_key} ({file_size} bytes), "
                    f"total: {self._current_size / 1024 / 1024:.1f}MB"
                )
                return cache_path

            except Exception as e:
                logger.warning(f"Failed to cache file {r2_key}: {e}")
                return None

    def invalidate(self, r2_key: str) -> bool:
        """
        Удалить файл из кэша.

        Args:
            r2_key: R2 ключ объекта

        Returns:
            True если файл был удалён
        """
        with self._lock:
            entry = self._index.get(r2_key)
            if entry is None:
                return False

            try:
                cache_path = Path(entry.path)
                if cache_path.exists():
                    cache_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete cached file: {e}")

            self._current_size -= entry.size
            del self._index[r2_key]
            self._save_index()

            logger.debug(f"R2DiskCache invalidate: {r2_key}")
            return True

    def invalidate_prefix(self, prefix: str) -> int:
        """
        Удалить все файлы с заданным префиксом из кэша.

        Args:
            prefix: Префикс R2 ключей для удаления

        Returns:
            Количество удалённых файлов
        """
        with self._lock:
            keys_to_remove = [
                k for k in self._index if k.startswith(prefix)
            ]

            for key in keys_to_remove:
                entry = self._index[key]
                try:
                    cache_path = Path(entry.path)
                    if cache_path.exists():
                        cache_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete cached file: {e}")

                self._current_size -= entry.size
                del self._index[key]

            if keys_to_remove:
                self._save_index()
                logger.debug(
                    f"R2DiskCache invalidate_prefix: {prefix}, "
                    f"removed {len(keys_to_remove)} files"
                )

            return len(keys_to_remove)

    def _ensure_space(self, needed: int) -> None:
        """
        Освободить место в кэше для нового файла (LRU eviction).

        Args:
            needed: Требуемое место в байтах
        """
        if self._current_size + needed <= self._max_size:
            return

        # Сортируем по времени доступа (старые первыми)
        entries = sorted(
            self._index.items(),
            key=lambda x: x[1].accessed
        )

        freed = 0
        keys_to_remove = []

        for r2_key, entry in entries:
            if self._current_size + needed - freed <= self._max_size:
                break

            keys_to_remove.append(r2_key)
            freed += entry.size

        # Удаляем файлы
        for key in keys_to_remove:
            entry = self._index[key]
            try:
                cache_path = Path(entry.path)
                if cache_path.exists():
                    cache_path.unlink()
            except Exception as e:
                logger.warning(f"LRU eviction failed for {key}: {e}")

            self._current_size -= entry.size
            del self._index[key]

        if keys_to_remove:
            logger.info(
                f"R2DiskCache LRU eviction: removed {len(keys_to_remove)} files, "
                f"freed {freed / 1024 / 1024:.1f}MB"
            )

    def clear(self) -> None:
        """Очистить весь кэш"""
        with self._lock:
            for entry in self._index.values():
                try:
                    cache_path = Path(entry.path)
                    if cache_path.exists():
                        cache_path.unlink()
                except Exception:
                    pass

            self._index.clear()
            self._current_size = 0
            self._save_index()

            logger.info("R2DiskCache cleared")

    def stats(self) -> dict:
        """
        Получить статистику кэша.

        Returns:
            Dict со статистикой
        """
        with self._lock:
            return {
                "entries_count": len(self._index),
                "current_size_bytes": self._current_size,
                "current_size_mb": self._current_size / 1024 / 1024,
                "max_size_bytes": self._max_size,
                "max_size_mb": self._max_size / 1024 / 1024,
                "usage_percent": (
                    self._current_size / self._max_size * 100
                    if self._max_size > 0 else 0
                ),
                "cache_dir": str(self._cache_dir),
            }


# Глобальный экземпляр кэша (синглтон)
_disk_cache_instance: Optional[R2DiskCache] = None
_disk_cache_lock = threading.Lock()


def get_disk_cache() -> R2DiskCache:
    """
    Получить глобальный экземпляр дискового кэша.

    Returns:
        R2DiskCache instance
    """
    global _disk_cache_instance
    if _disk_cache_instance is None:
        with _disk_cache_lock:
            if _disk_cache_instance is None:
                _disk_cache_instance = R2DiskCache()
    return _disk_cache_instance
