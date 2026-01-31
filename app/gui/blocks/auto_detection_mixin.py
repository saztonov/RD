"""Миксин для автоматической детекции блоков через Block Detection API."""
from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.block_detection_client import (
    BlockDetectionClient,
    BlockDetectionConnectionError,
    BlockDetectionError,
    BlockDetectionTimeoutError,
    DetectionResult,
)
from app.gui.toast import show_toast
from rd_core.models import Block, BlockSource, BlockType, ShapeType

if TYPE_CHECKING:
    from rd_core.models import Page

logger = logging.getLogger(__name__)


class AutoDetectionMixin:
    """Миксин для автоматической детекции блоков на странице."""

    # ThreadPoolExecutor для фоновых операций
    _detection_executor: Optional[ThreadPoolExecutor] = None

    def _get_detection_executor(self) -> ThreadPoolExecutor:
        """Получить или создать executor для детекции."""
        if self._detection_executor is None:
            self._detection_executor = ThreadPoolExecutor(max_workers=1)
        return self._detection_executor

    def _auto_detect_blocks(self):
        """Запустить автоматическую детекцию блоков на текущей странице."""
        # Проверка: PDF открыт?
        if not self.pdf_document:
            show_toast(self, "Откройте PDF документ", success=False)
            return

        if not self.annotation_document:
            show_toast(self, "Нет документа разметки", success=False)
            return

        # Проверка блокировки документа
        if self._check_document_locked_for_editing():
            return

        # Получить настройки
        settings = self._get_block_detection_settings()
        if not settings.get("enabled", True):
            show_toast(self, "Авто-детекция отключена в настройках", success=False)
            return

        # Проверить есть ли блоки на странице
        current_page_data = self._get_or_create_page(self.current_page)
        if current_page_data and current_page_data.blocks:
            action = self._show_existing_blocks_dialog(len(current_page_data.blocks))
            if action == "cancel":
                return
            elif action == "replace":
                # Сохраняем undo перед очисткой
                self._save_undo_state()
                current_page_data.blocks.clear()
                self.page_viewer.set_blocks([])
            elif action == "add":
                # Сохраняем undo перед добавлением
                self._save_undo_state()
        else:
            # Сохраняем undo state
            self._save_undo_state()

        # Показать прогресс
        self._show_detection_progress()

        # Запустить в фоновом потоке
        executor = self._get_detection_executor()
        executor.submit(self._run_detection_in_thread, settings)

    def _get_block_detection_settings(self) -> dict:
        """Получить настройки Block Detection из OCRSettings."""
        try:
            from app.gui.ocr_settings.dialog import OCRSettingsDialog
            from app.tree_client.core import _get_tree_client

            # Попробуем загрузить настройки из Supabase
            import os

            supabase_url = os.getenv("SUPABASE_URL", "")
            supabase_key = os.getenv("SUPABASE_KEY", "")

            if supabase_url and supabase_key:
                url = f"{supabase_url}/rest/v1/app_settings?key=eq.{OCRSettingsDialog.SETTINGS_KEY}"
                headers = {
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                }
                client = _get_tree_client()
                resp = client.get(url, headers=headers, timeout=5.0)

                if resp.status_code == 200:
                    data = resp.json()
                    if data and len(data) > 0:
                        settings_data = data[0].get("value", {})
                        return {
                            "enabled": settings_data.get("block_detection_enabled", True),
                            "url": settings_data.get(
                                "block_detection_url", "http://localhost:8000"
                            ),
                            "timeout": settings_data.get("block_detection_timeout", 60),
                        }
        except Exception as e:
            logger.debug(f"Не удалось загрузить настройки из БД: {e}")

        # Fallback на значения по умолчанию или env
        import os

        return {
            "enabled": True,
            "url": os.getenv("BLOCK_DETECTION_URL", "http://localhost:8000"),
            "timeout": 60,
        }

    def _show_existing_blocks_dialog(self, block_count: int) -> str:
        """
        Показать диалог при наличии существующих блоков.

        Returns:
            "add" - добавить к существующим
            "replace" - заменить все
            "cancel" - отменить
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("Авто-разметка")
        msg.setText(f"На странице уже есть {block_count} блок(ов).")
        msg.setInformativeText("Что сделать с новыми блоками?")

        add_btn = msg.addButton("Добавить к существующим", QMessageBox.AcceptRole)
        replace_btn = msg.addButton("Заменить все", QMessageBox.DestructiveRole)
        msg.addButton("Отмена", QMessageBox.RejectRole)

        msg.exec()

        clicked = msg.clickedButton()
        if clicked == add_btn:
            return "add"
        elif clicked == replace_btn:
            return "replace"
        return "cancel"

    def _show_detection_progress(self):
        """Показать индикатор прогресса."""
        if hasattr(self, "_status_label"):
            self._status_label.setText("Авто-разметка...")
        if hasattr(self, "_status_progress"):
            self._status_progress.setMaximum(0)  # Indeterminate
            self._status_progress.show()

    def _hide_detection_progress(self):
        """Скрыть индикатор прогресса."""
        if hasattr(self, "hide_transfer_progress"):
            self.hide_transfer_progress()
        elif hasattr(self, "_status_progress"):
            self._status_progress.hide()
        if hasattr(self, "_status_label"):
            self._status_label.setText("")

    def _run_detection_in_thread(self, settings: dict):
        """Выполнить детекцию в фоновом потоке."""
        try:
            # Рендерим текущую страницу в PNG
            page_image = self.page_images.get(self.current_page)
            if page_image is None:
                # Рендерим страницу
                page_image = self.pdf_document.render_page(self.current_page)
                if page_image is None:
                    QTimer.singleShot(
                        0, lambda: self._on_detection_error("Не удалось отрендерить страницу")
                    )
                    return

            # Конвертируем PIL Image в bytes
            buffer = io.BytesIO()
            page_image.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()

            page_width = page_image.width
            page_height = page_image.height

            logger.info(
                f"Отправка страницы на детекцию: {page_width}x{page_height}, "
                f"{len(image_bytes)} байт"
            )

            # Создаём клиент и отправляем запрос
            client = BlockDetectionClient(
                base_url=settings["url"],
                timeout=float(settings["timeout"]),
            )

            result = client.detect_blocks(image_bytes)

            # Применяем результат в main thread
            QTimer.singleShot(
                0,
                lambda: self._apply_detected_blocks(result, page_width, page_height),
            )

        except BlockDetectionConnectionError:
            QTimer.singleShot(
                0,
                lambda: self._on_detection_error("Сервер детекции недоступен"),
            )
        except BlockDetectionTimeoutError:
            QTimer.singleShot(
                0,
                lambda: self._on_detection_error("Превышено время ожидания"),
            )
        except BlockDetectionError as e:
            QTimer.singleShot(
                0,
                lambda: self._on_detection_error(str(e)),
            )
        except Exception as e:
            logger.error(f"Ошибка детекции: {e}", exc_info=True)
            error_msg = str(e)[:100]
            QTimer.singleShot(
                0,
                lambda: self._on_detection_error(error_msg),
            )

    def _apply_detected_blocks(
        self,
        result: DetectionResult,
        page_width: int,
        page_height: int,
    ):
        """Применить результаты детекции - добавить блоки на страницу."""
        self._hide_detection_progress()

        if not result.blocks:
            show_toast(self, "Блоки не найдены", success=True)
            return

        current_page_data = self._get_or_create_page(self.current_page)
        if not current_page_data:
            show_toast(self, "Ошибка: нет данных страницы", success=False)
            return

        added_count = 0

        for detected in result.blocks:
            try:
                # Конвертируем нормализованные координаты в пиксели
                x1, y1, x2, y2 = detected.bounding_box
                coords_px = (
                    int(x1 * page_width),
                    int(y1 * page_height),
                    int(x2 * page_width),
                    int(y2 * page_height),
                )

                # Проверяем что координаты валидны
                if coords_px[2] <= coords_px[0] or coords_px[3] <= coords_px[1]:
                    logger.warning(f"Пропущен блок с невалидными координатами: {coords_px}")
                    continue

                # Маппим тип блока
                block_type = self._map_api_block_type(detected.block_type)

                # Создаём Block
                block = Block.create(
                    page_index=self.current_page,
                    coords_px=coords_px,
                    page_width=page_width,
                    page_height=page_height,
                    block_type=block_type,
                    source=BlockSource.AUTO,
                    shape_type=ShapeType.RECTANGLE,
                )

                current_page_data.blocks.append(block)
                added_count += 1

            except Exception as e:
                logger.warning(f"Ошибка при создании блока: {e}")
                continue

        if added_count == 0:
            show_toast(self, "Не удалось добавить блоки", success=False)
            return

        # Обновляем UI
        self.page_viewer.set_blocks(current_page_data.blocks)
        QTimer.singleShot(0, self.blocks_tree_manager.update_blocks_tree)
        self._auto_save_annotation()

        logger.info(f"Добавлено {added_count} блоков через авто-детекцию")
        show_toast(self, f"Найдено {added_count} блоков", success=True)

    def _map_api_block_type(self, api_type: str) -> BlockType:
        """Маппинг типов блоков API -> BlockType."""
        mapping = {
            "text": BlockType.TEXT,
            "table": BlockType.TEXT,  # TABLE -> TEXT
            "image": BlockType.IMAGE,
            "unknown": BlockType.TEXT,
        }
        return mapping.get(api_type.lower(), BlockType.TEXT)

    def _on_detection_error(self, error_msg: str):
        """Обработка ошибки детекции."""
        self._hide_detection_progress()
        logger.error(f"Ошибка авто-детекции: {error_msg}")
        show_toast(self, f"Ошибка: {error_msg[:50]}", success=False)
